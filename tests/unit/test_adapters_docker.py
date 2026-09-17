"""B2: Docker API адаптер — нормализация и маппинг без docker-демона.

Покрываем `_format_ports` / `_normalize_filters` (чистые функции), connect/ping,
контейнеры (list/logs/info/stats), events, system_df, prune и disconnect.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_linx.adapters.docker import DockerAdapter


class _FakeImage:
    def __init__(self, tags: list[str] | None = None, image_id: str = "sha256:beef") -> None:
        self.tags = tags or []
        self.id = image_id


class _FakeContainer:
    def __init__(self, **over: Any) -> None:
        self.id = over.get("id", "c" * 64)
        self.short_id = over.get("short_id", "c" * 12)
        self.name = over.get("name", "web")
        self.status = over.get("status", "running")
        self.image = over.get("image", _FakeImage(["nginx:latest"]))
        self.ports = over.get("ports", {})
        self.attrs = over.get("attrs", {})
        self._logs = over.get("logs", b"line1\nline2\n")
        self._stats = over.get("stats", {})
        self.logs_kwargs: dict[str, Any] | None = None

    def logs(self, **kwargs: Any) -> bytes:
        self.logs_kwargs = kwargs
        return self._logs

    def stats(self, stream: bool = False) -> dict[str, Any]:
        return self._stats


_STATS = {
    "cpu_stats": {"cpu_usage": {"total_usage": 300}, "system_cpu_usage": 1000},
    "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
    "memory_stats": {"usage": 1000, "cache": 200, "limit": 4000},
    "networks": {"eth0": {"rx_bytes": 10}},
}


@pytest.fixture()
def install_docker(monkeypatch):
    """Установить фейковый `docker.DockerClient`; вернуть (модуль, клиенты, классы)."""
    import mcp_linx.adapters.docker as mod

    def _install(
        containers: list[_FakeContainer] | None = None,
        df: dict[str, Any] | None = None,
    ):
        instances: list[Any] = []

        class FakeContainers:
            last_list: dict[str, Any] | None = None
            last_prune: dict[str, Any] | None = None

            def list(self, all: bool = True, filters: dict[str, Any] | None = None):
                FakeContainers.last_list = {"all": all, "filters": filters}
                return list(containers or [])

            def get(self, container_id: str) -> _FakeContainer:
                for container in containers or []:
                    if container.id == container_id:
                        return container
                raise KeyError(container_id)

            def prune(self, filters: dict[str, Any] | None = None):
                FakeContainers.last_prune = filters
                return {"SpaceReclaimed": 1024, "ContainersDeleted": ["dead"]}

        class FakeApi:
            def df(self):
                return df or {}

        class FakeClient:
            last_events_kwargs: dict[str, Any] | None = None
            ping_raises = False

            def __init__(self, base_url: str | None = None, timeout: int | None = None):
                self.base_url = base_url
                self.timeout = timeout
                self.ping_calls = 0
                self.closed = False
                self.containers = FakeContainers()
                self.api = FakeApi()
                instances.append(self)

            def ping(self):
                self.ping_calls += 1
                if FakeClient.ping_raises:
                    raise ConnectionError("no daemon")

            def events(self, **kwargs: Any):
                FakeClient.last_events_kwargs = kwargs
                return iter([{"Action": f"ev{i}"} for i in range(25)])

            def close(self):
                self.closed = True

        monkeypatch.setattr(mod.docker, "DockerClient", FakeClient)
        return mod, instances, FakeClient, FakeContainers

    return _install


class TestConnect:
    @pytest.mark.asyncio
    async def test_uses_config_base_url_and_timeout(self, install_docker):
        mod, instances, _, _ = install_docker()
        adapter = mod.DockerAdapter({"host": "tcp://docker:2375", "timeout_seconds": 7})

        await adapter.connect()

        assert instances[0].base_url == "tcp://docker:2375"
        assert instances[0].timeout == 7
        assert instances[0].ping_calls == 1
        assert adapter._client is instances[0]

    @pytest.mark.asyncio
    async def test_defaults_to_unix_socket_and_10s(self, install_docker):
        mod, instances, _, _ = install_docker()

        await mod.DockerAdapter().connect()

        assert instances[0].base_url == "unix:///var/run/docker.sock"
        assert instances[0].timeout == 10

    @pytest.mark.asyncio
    async def test_ping_true_and_false(self, install_docker):
        mod, instances, client_cls, _ = install_docker()
        adapter = mod.DockerAdapter()

        assert await adapter.ping() is True  # lazy connect

        client_cls.ping_raises = True
        instances[0].ping_calls = 0
        assert await adapter.ping() is False

    @pytest.mark.asyncio
    async def test_disconnect_closes_and_resets(self, install_docker):
        mod, instances, _, _ = install_docker()
        adapter = mod.DockerAdapter()
        await adapter.connect()

        await adapter.disconnect()

        assert instances[0].closed is True
        assert adapter._client is None


class TestContainers:
    @pytest.mark.asyncio
    async def test_list_mapping_filters_and_limit(self, install_docker):
        container = _FakeContainer(
            ports={"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
            attrs={
                "NetworkSettings": {"Networks": {"bridge": {}}},
                "Created": "2026-01-01T00:00:00Z",
                "Path": "/docker-entrypoint.sh",
                "Args": ["nginx", "-g", "daemon off;"],
                "Config": {"Env": ["TZ=UTC"], "Labels": {"role": "web"}},
            },
        )
        mod, _, _, containers_cls = install_docker([container])
        adapter = mod.DockerAdapter()

        result = await adapter.list_containers(filters={"status": "running"}, limit=1)

        assert len(result) == 1
        assert result[0]["name"] == "web"
        assert result[0]["image"] == "nginx:latest"
        assert result[0]["ports"] == [
            {"container_port": "80/tcp", "host_ip": "0.0.0.0", "host_port": "8080"}
        ]
        assert result[0]["networks"] == ["bridge"]
        assert result[0]["command"] == "/docker-entrypoint.sh nginx -g daemon off;"
        assert result[0]["environment"] == ["TZ=UTC"]
        assert result[0]["labels"] == {"role": "web"}
        # Docker API ждёт значения-списки
        assert containers_cls.last_list == {"all": True, "filters": {"status": ["running"]}}

    @pytest.mark.asyncio
    async def test_image_falls_back_to_id_without_tags(self, install_docker):
        container = _FakeContainer(image=_FakeImage([], image_id="sha256:untagged"))
        mod, _, _, _ = install_docker([container])

        result = await mod.DockerAdapter().list_containers()

        assert result[0]["image"] == "sha256:untagged"

    @pytest.mark.asyncio
    async def test_limit_zero_means_no_truncation(self, install_docker):
        mod, _, _, _ = install_docker([_FakeContainer(name="a"), _FakeContainer(name="b")])

        result = await mod.DockerAdapter().list_containers(limit=0)

        assert [c["name"] for c in result] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_logs_decoded_and_kwargs_passed(self, install_docker):
        container = _FakeContainer(logs=b"2026-01-01 line\n")
        mod, _, _, _ = install_docker([container])
        adapter = mod.DockerAdapter()
        await adapter.connect()

        result = await adapter.get_container_logs(container.id, tail=25, since="2026-01-01")

        assert result == {"stdout": "2026-01-01 line\n", "container_id": container.id, "tail": 25}
        assert container.logs_kwargs == {"tail": 25, "since": "2026-01-01", "timestamps": True}

    @pytest.mark.asyncio
    async def test_container_info_returns_attrs_copy(self, install_docker):
        container = _FakeContainer(attrs={"Id": "abc", "State": {"Running": True}})
        mod, _, _, _ = install_docker([container])
        adapter = mod.DockerAdapter()
        await adapter.connect()

        info = await adapter.get_container_info(container.id)

        assert info == {"Id": "abc", "State": {"Running": True}}
        info["Id"] = "mutated"
        assert container.attrs["Id"] == "abc"  # копия, не ссылка

    @pytest.mark.asyncio
    async def test_container_stats_cpu_and_memory_math(self, install_docker):
        container = _FakeContainer(stats=_STATS)
        mod, _, _, _ = install_docker([container])
        adapter = mod.DockerAdapter()
        await adapter.connect()

        stats = await adapter.get_container_stats(container.id)

        assert stats["cpu_percent"] == 40.0  # (300-100)/(1000-500)*100
        assert stats["memory_usage_bytes"] == 800  # 1000 - cache 200
        assert stats["memory_percent"] == 20.0  # 800/4000*100
        assert stats["network"] == {"eth0": {"rx_bytes": 10}}

    @pytest.mark.asyncio
    async def test_container_stats_zero_deltas(self, install_docker):
        container = _FakeContainer(
            stats={
                "cpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
                "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
                "memory_stats": {"usage": 0, "limit": 0},
            }
        )
        mod, _, _, _ = install_docker([container])
        adapter = mod.DockerAdapter()
        await adapter.connect()

        stats = await adapter.get_container_stats(container.id)

        assert stats["cpu_percent"] == 0.0
        assert stats["memory_percent"] == 0.0


class TestEventsSystemAndPrune:
    @pytest.mark.asyncio
    async def test_events_list_filter_becomes_type(self, install_docker):
        mod, _, client_cls, _ = install_docker()
        adapter = mod.DockerAdapter()
        await adapter.connect()

        events = await adapter.get_events(event_filters=["container"])

        assert client_cls.last_events_kwargs == {"filters": {"type": ["container"]}, "decode": True}
        assert len(events) == 20  # кап на 20 событий

    @pytest.mark.asyncio
    async def test_events_dict_filter_and_since_until(self, install_docker):
        mod, _, client_cls, _ = install_docker()
        adapter = mod.DockerAdapter()
        await adapter.connect()

        await adapter.get_events(since="1h", until="now", event_filters={"label": "app=web"})

        assert client_cls.last_events_kwargs == {
            "filters": {"label": "app=web"},  # dict-фильтр передаётся как есть
            "decode": True,
            "since": "1h",
            "until": "now",
        }

    @pytest.mark.asyncio
    async def test_system_df_counts(self, install_docker):
        mod, _, _, _ = install_docker(df={"Containers": [1, 2], "Images": [1], "Volumes": []})
        adapter = mod.DockerAdapter()
        await adapter.connect()

        df = await adapter.system_df()

        assert df == {
            "Containers": {"count": 2},
            "Images": {"count": 1},
            "Volumes": {"count": 0},
        }

    @pytest.mark.asyncio
    async def test_prune_containers_mapping(self, install_docker):
        mod, _, _, containers_cls = install_docker()
        adapter = mod.DockerAdapter()
        await adapter.connect()

        result = await adapter.prune_containers(filters={"status": "exited"})

        assert result == {"SpaceReclaimed": 1024, "ContainersDeleted": ["dead"]}
        assert containers_cls.last_prune == {"status": "exited"}


class TestPureHelpers:
    def test_format_ports_empty_and_list_passthrough(self):
        assert DockerAdapter._format_ports(None) == []
        assert DockerAdapter._format_ports({}) == []
        assert DockerAdapter._format_ports([{"container_port": "80"}]) == [{"container_port": "80"}]

    def test_format_ports_dict_without_binding(self):
        assert DockerAdapter._format_ports({"8080/tcp": None}) == [
            {"container_port": "8080/tcp", "host_ip": None, "host_port": None}
        ]

    def test_format_ports_multiple_bindings(self):
        assert DockerAdapter._format_ports(
            {
                "5432/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": "5432"},
                    {"HostIp": "::", "HostPort": "5433"},
                ]
            }
        ) == [
            {"container_port": "5432/tcp", "host_ip": "127.0.0.1", "host_port": "5432"},
            {"container_port": "5432/tcp", "host_ip": "::", "host_port": "5433"},
        ]

    def test_normalize_filters(self):
        assert DockerAdapter._normalize_filters(None) == {}
        assert DockerAdapter._normalize_filters({"status": "running"}) == {"status": ["running"]}
        assert DockerAdapter._normalize_filters({"status": ["a", "b"]}) == {"status": ["a", "b"]}
        assert DockerAdapter._normalize_filters({"label": {"a": "b"}}) == {"label": {"a": "b"}}
