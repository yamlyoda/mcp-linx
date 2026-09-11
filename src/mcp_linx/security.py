"""Security guard для MCP-Linx"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator


class SecurityError(Exception):
    """Ошибка безопасности"""

    pass


class SecurityGuard:
    """Гuard для безопасности операций MCP-Linx"""

    # Запрещенные команды и паттерны
    DANGEROUS_PATTERNS = [
        r"\brm\s+-rf\s+/\b",
        r"\brm\s+-rf\s+/\s*",
        r"\bmkfs\b",
        r"\bdd\s+if=\s*/dev/[a-z]+\s+of=/dev/",
        r":(){ :|:& };:",
        r"\bwget\b.*\bcurl\b",
        r"\bcurl\b.*\bsh\b",
        r"\bchmod\s+777\s+/",
        r"\bchown\s+-R\s+root",
        r"\b>\s*/dev/sda",
        r"\b>\s*/dev/sdb",
        r"\b>\s*/dev/nvme",
    ]

    # Read-only команды
    READONLY_COMMANDS = [
        "cat",
        "ls",
        "ps",
        "top",
        "htop",
        "free",
        "df",
        "du",
        "ip",
        "ss",
        "netstat",
        "ping",
        "traceroute",
        "curl",
        "wget",
        "journalctl",
        "dmesg",
        "grep",
        "awk",
        "sed",
        "tail",
        "head",
        "mount",
        "fdisk",
        "lsblk",
        "lsof",
        "nmcli",
        "systemctl",
        "service",
        "docker",
        "psql",
        "pg_isready",
        "nginx",
        "curl",
        "uname",
        "uptime",
        "nproc",
        "vmstat",
        "swapon",
        "vm_stat",
        "sysctl",
        "redis-cli",
        "kubectl",
        "systemd-analyze",
        # P0 (INCIDENT_504): read-only подкоманды диагностики firewall/eBPF
        "bpftool",
        "nft",
        "iptables",
        "ufw",
    ]

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._readonly = self._config.get("readonly", True)
        self._max_output_size = int(self._config.get("max_command_output_size", 10000))
        self._max_log_lines = int(self._config.get("max_log_lines", 500))
        self._max_search_results = int(self._config.get("max_search_results", 100))
        self._command_timeout = int(self._config.get("command_timeout_seconds", 30))
        self._allowed_hosts = set(self._config.get("allowed_hosts", ["localhost"]))

    def validate_command(self, command: str) -> None:
        """Валидация команды на опасные операции

        Raises:
            SecurityError: если команда опасна
        """
        if self._readonly and not self._is_readonly_command(command):
            raise SecurityError(f"Write operations are not allowed in read-only mode: {command}")

        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise SecurityError(f"Potentially dangerous command blocked: {command}")

    def _is_readonly_command(self, command: str) -> bool:
        """Проверка, является ли команда read-only"""
        tokens = command.split()
        if not tokens:
            return False

        base_command = tokens[0].split("/")[-1]  # путь к команде

        if base_command in self.READONLY_COMMANDS:
            return True

        # docker exec/logs/inspect и т.п. — read-only операции
        return (
            base_command in ["docker", "kubectl"]
            and len(tokens) > 1
            and tokens[1]
            in [
                "exec",
                "logs",
                "inspect",
                "stats",
                "top",
                "port",
            ]
        )

    def validate_input(self, schema: type[BaseModel], data: dict[str, Any]) -> BaseModel:
        """Валидация входных данных по Pydantic схеме

        Raises:
            ValidationError: если данные не валидны
        """
        try:
            return schema(**data)
        except ValidationError:
            raise  # Просто пробрасываем оригинальную ошибку

    def limit_output(self, data: Any, max_size: int | None = None) -> Any:
        """Ограничение размера вывода

        Args:
            data: Данные для ограничения
            max_size: Максимальный размер (байты)
        """
        max_size = max_size or self._max_output_size

        if isinstance(data, str):
            if len(data) > max_size:
                return data[:max_size] + f"\n... [truncated, total size: {len(data)} bytes]"
            return data

        if isinstance(data, (list, dict)):
            data_str = str(data)
            if len(data_str) > max_size:
                return f"[truncated, total size: {len(data)} objects/bytes, exceeds limit of {max_size} bytes]"

        return data

    def limit_log_lines(self, logs: str) -> str:
        """Ограничение кол-ва строк лога"""
        lines = logs.splitlines()
        if len(lines) > self._max_log_lines:
            return (
                "\n".join(lines[: self._max_log_lines])
                + f"\n... [truncated, total lines: {len(lines)}]"
            )
        return logs

    def validate_host(self, host: str) -> None:
        """Валидация хоста для доступа

        Raises:
            SecurityError: если хост не в whitelist
        """
        if self._allowed_hosts and host not in self._allowed_hosts:
            raise SecurityError(f"Host {host} is not in allowed_hosts list")

    def apply_timeout(self, func: Any, timeout: int | None = None) -> Any:
        """Применение таймаута к функции (async)"""
        timeout = timeout or self._command_timeout
        # В реальности — обернуть в asyncio.wait_for
        return func


class CommandInput(BaseModel):
    """Входные данные для выполнения команды"""

    command: str
    timeout: int = 30
    host: str | None = None

    @field_validator("command")
    @classmethod
    def validate_command_not_empty(cls, v: str) -> str:
        """Команда не должна быть пустой"""
        if not v or not v.strip():
            raise ValueError("Command cannot be empty")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout_positive(cls, v: int) -> int:
        """Таймаут должен быть положительным"""
        if v < 1:
            raise ValueError("Timeout must be positive (>= 1)")
        return v


class LogInput(BaseModel):
    """Входные данные для чтения логов"""

    path: str
    lines: int = 100
    since: str | None = None
    pattern: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path_not_empty(cls, v: str) -> str:
        """Путь не должен быть пустым"""
        if not v or not v.strip():
            raise ValueError("Path cannot be empty")
        return v

    @field_validator("lines")
    @classmethod
    def validate_lines_positive(cls, v: int) -> int:
        """Количество строк должно быть положительным"""
        if v < 1:
            raise ValueError("Lines must be positive (>= 1)")
        return v
