# syntax=docker/dockerfile:1
# =============================================================================
# MCP-Linx — MCP-сервер диагностики Linux-инфраструктуры.
#
# Модель запуска A (по умолчанию, безопасная): изолированный контейнер
# диагностирует УДАЛЁННЫЕ хосты по SSH (SSHAdapter), а postgres/redis/
# prometheus/loki/k8s — по сети.
#
# Модель запуска B (диагностика самого хоста, только Linux): см.
# docker-compose.yml, профиль "host" — требует pid/network host + read-only
# маунты. docker.sock внутри контейнера = root-доступ к хосту Docker.
# =============================================================================

# ---------- Stage 1: сборка wheel ----------
FROM python:3.11-slim AS builder

# Для корпоративных сетей с TLS-инспекцией: сборка с
# --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org"
# (отключает проверку сертификата pip; в CI/обычных сетях не задавайте)
ARG PIP_TRUSTED_HOST=""

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

WORKDIR /build

# gcc нужен только для сборки колёс (psycopg2 и пр.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip wheel --no-deps --wheel-dir /wheels .

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ARG PIP_TRUSTED_HOST=""

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PYTHONUNBUFFERED=1

# Утилиты диагностики, доступные внутри контейнера (модель A):
#   openssh-client — SSHAdapter (ssh к целевым хостам)
#   postgresql-client / redis-tools — pg_* / redis_* плагины по сети
#   iproute2 (ss), dnsutils (dig), procps (ps), curl — netdiag и linux-проверки
# kubectl/jq не включены ради размера образа; при необходимости добавьте.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-client \
        ca-certificates \
        curl \
        postgresql-client \
        redis-tools \
        iproute2 \
        dnsutils \
        procps \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN groupadd -r mcp \
    && useradd -r -g mcp -m -d /home/mcp -s /usr/sbin/nologin mcp \
    && mkdir -p /home/mcp/.ssh && chown mcp:mcp /home/mcp/.ssh

WORKDIR /app

# Wheel из builder
# Wheel из builder
COPY --from=builder /wheels/*.whl /tmp/
# Build-only tooling, вытекшее из python:3.11-slim (wheel 0.45.1 → CVE-2026-24049,
# setuptools→jaraco.context 5.3.0 → CVE-2026-23949), не нужно рантайму: ни src/,
# ни tests/ не используют pkg_resources/importlib.metadata → удаляем из образа.
RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -f /tmp/*.whl \
    && pip uninstall -y setuptools wheel || true

# Конфиг по умолчанию (переопределяйте маунтом: -v ./config:/app/config:ro)
COPY config/ /app/config/
RUN chown -R mcp:mcp /app/config

USER mcp

# pydantic-settings читает поле config_path из env CONFIG_PATH
ENV CONFIG_PATH=/app/config/settings.yaml

# stdio-транспорт MCP: Claude Desktop / Inspector используют docker run -i
ENTRYPOINT ["python", "-m", "mcp_linx.main"]
