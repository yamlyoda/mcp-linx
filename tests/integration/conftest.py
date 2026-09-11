"""Fixtures for integration tests (require Docker)."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

COMPOSE_FILE = Path(__file__).parent.parent / "docker-compose.test.yml"
NGINX_CONF = Path(__file__).parent.parent / "nginx-test.conf"
PROJECT_NAME = "mcp-linx-test"


def docker_available() -> bool:
    """Проверка доступности Docker daemon."""
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=True,
        )
        return True
    except Exception:
        return False


def compose_up() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT_NAME, "up", "-d"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker compose up failed ({result.returncode}):\n"
            f"STDOUT: {result.stdout[-2000:]}\nSTDERR: {result.stderr[-2000:]}"
        )


def compose_down() -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            PROJECT_NAME,
            "down",
            "--remove-orphans",
        ],
        capture_output=True,
    )


@pytest.fixture(scope="module")
def docker_stack():
    """Поднять тестовый стек (postgres/nginx/redis) и снести после модуля."""
    if not docker_available():
        pytest.skip("Docker is not available — integration tests skipped")

    compose_down()  # чистое состояние
    compose_up()
    try:
        yield
    finally:
        compose_down()


def wait_for_postgres(host: str, port: int, timeout: float = 45.0) -> None:
    """Ждать, пока PostgreSQL не начнёт принимать соединения."""
    import psycopg2

    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user="test",
                password="testpass",
                database="testdb",
                connect_timeout=3,
            )
            conn.close()
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1)
    raise TimeoutError(f"PostgreSQL on {host}:{port} not ready: {last_err}")


def wait_for_http(url: str, timeout: float = 30.0) -> None:
    """Ждать, пока URL не начнёт отдавать 200."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=3.0)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"HTTP endpoint {url} not ready within {timeout}s")


@pytest.fixture(scope="module")
def postgres_dsn(docker_stack) -> str:
    """DSN: host=localhost port=54321 (mapped)."""
    wait_for_postgres("localhost", 54321)
    return "localhost", 54321


@pytest.fixture(scope="module")
def nginx_base_url(docker_stack) -> str:
    wait_for_http("http://127.0.0.1:18080/")
    return "http://127.0.0.1:18080"


@pytest.fixture(scope="module")
def redis_port(docker_stack) -> int:
    # Проверяем доступность redis через TCP
    import socket

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 16379), timeout=2):
                return 16379
        except OSError:
            time.sleep(0.5)
    raise TimeoutError("Redis on 16379 not ready")


@pytest.fixture(scope="module")
def redis_cli_available() -> bool:
    """Доступен ли redis-cli на хосте (нужен RedisPlugin)."""
    return shutil.which("redis-cli") is not None
