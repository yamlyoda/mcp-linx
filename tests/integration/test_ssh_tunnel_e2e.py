"""Wave 13 (C2): E2/E3 end-to-end на реальном SSH-сервере (opt-in).

Тест включается только при заданных переменных окружения, поэтому CI (где нет
SSH-хоста) его пропускает. Проверяем настоящий форвардинг: `SSHTunnel` открывает
локальный порт, и через него доступен SSH-баннер удалённого хоста.

Запуск (пример):

    MCP_LINX_SSH_HOST=10.0.0.5 \
    MCP_LINX_SSH_USER=ops \
    MCP_LINX_SSH_KEY=~/.ssh/id_rsa \
    pytest -m integration tests/integration/test_ssh_tunnel_e2e.py -q

Опционально: `MCP_LINX_SSH_PORT` (по умолчанию 22),
`MCP_LINX_SSH_REMOTE_PORT` (порт на стороне SSH-сервера, по умолчанию 22 —
то есть форвард на сам sshd), `MCP_LINX_SSH_JUMP` (бастион, проверка E3).
"""

from __future__ import annotations

import os
import socket

import pytest

from mcp_linx.adapters.ssh_pool import SSHConnectionPool, SSHTunnel

pytestmark = pytest.mark.integration

_REQUIRED = ("MCP_LINX_SSH_HOST", "MCP_LINX_SSH_USER")


def _ssh_config() -> dict[str, object]:
    host = os.environ["MCP_LINX_SSH_HOST"]
    config: dict[str, object] = {
        "host": host,
        "port": int(os.environ.get("MCP_LINX_SSH_PORT", "22")),
        "username": os.environ["MCP_LINX_SSH_USER"],
        "host_key_policy": os.environ.get("MCP_LINX_SSH_HOST_KEY_POLICY", "auto_add"),
    }
    if key := os.environ.get("MCP_LINX_SSH_KEY"):
        config["key_file"] = key
    if jump := os.environ.get("MCP_LINX_SSH_JUMP"):
        config["jump_host"] = jump
    return config


@pytest.fixture(scope="module")
def ssh_env() -> None:
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.skip(f"SSH target not configured (missing: {', '.join(missing)})")


@pytest.fixture()
def pool(ssh_env: None):
    pool = SSHConnectionPool()
    yield pool
    pool.close_all()


def test_command_execution_over_ssh(pool: SSHConnectionPool) -> None:
    """E1/E3: команда выполняется, результат и код возврата приходят наверх."""
    from mcp_linx.adapters.ssh_pool import exec_command_with_retry

    config = _ssh_config()

    result = exec_command_with_retry(pool, config, "echo MCP_LINX_E2E", timeout=10)

    assert result["returncode"] == 0
    assert "MCP_LINX_E2E" in result["stdout"]


def test_tunnel_forwards_to_remote_ssh_port(pool: SSHConnectionPool) -> None:
    """E2: локальный порт форвардится на удалённый, данные идут в обе стороны."""
    config = _ssh_config()
    client = pool.get(config)
    remote_port = int(os.environ.get("MCP_LINX_SSH_REMOTE_PORT", "22"))

    tunnel = SSHTunnel(client, str(config["host"]), remote_port)
    tunnel.start()
    try:
        host, port = tunnel.local_address
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.settimeout(10)
            banner = sock.recv(64)
        # Через туннель приходит SSH-баннер удалённого сервера.
        assert banner.startswith(b"SSH-"), banner
    finally:
        tunnel.stop()


def test_connection_pool_reuses_client(pool: SSHConnectionPool) -> None:
    """Переиспользование соединения: второй `get()` возвращает тот же клиент."""
    config = _ssh_config()

    first = pool.get(config)
    second = pool.get(config)

    assert first is second
