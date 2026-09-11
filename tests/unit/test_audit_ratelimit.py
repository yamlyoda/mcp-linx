"""Unit tests: audit logging + rate limiting"""

from __future__ import annotations

import json

import pytest


class TestSanitizeParams:
    def test_redacts_sensitive_keys(self):
        from mcp_linx.audit import sanitize_params

        params = {
            "host": "db.example.com",
            "password": "supersecret",
            "token": "abc123",
            "nested": {"api_key": "xyz", "safe": 42},
            "list": [{"secret": "s1"}, {"ok": True}],
            "normal": "value",
        }
        cleaned = sanitize_params(params)
        assert cleaned["password"] == "***REDACTED***"
        assert cleaned["token"] == "***REDACTED***"
        assert cleaned["nested"]["api_key"] == "***REDACTED***"
        assert cleaned["nested"]["safe"] == 42
        assert cleaned["list"][0]["secret"] == "***REDACTED***"
        assert cleaned["list"][1]["ok"] is True
        assert cleaned["host"] == "db.example.com"
        assert cleaned["normal"] == "value"


class TestAuditLogger:
    def test_disabled_writes_nothing(self, tmp_path):
        from mcp_linx.audit import AuditLogger

        log_file = tmp_path / "audit.jsonl"
        audit = AuditLogger(enabled=False, log_file=str(log_file))
        audit.log_call("tool", "plugin", {"a": 1}, "ok", 12.5)
        assert not log_file.exists()

    def test_writes_json_line_with_sanitized_params(self, tmp_path):
        from mcp_linx.audit import AuditLogger

        log_file = tmp_path / "audit.jsonl"
        audit = AuditLogger(enabled=True, log_file=str(log_file))
        audit.log_call(
            "pg_connections",
            "postgres",
            {"host": "db", "password": "hunter2"},
            "ok",
            3.14,
        )
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["tool"] == "pg_connections"
        assert record["plugin"] == "postgres"
        assert record["status"] == "ok"
        assert record["params"]["password"] == "***REDACTED***"
        assert record["params"]["host"] == "db"
        assert "duration_ms" in record

    def test_from_config_disabled_by_default(self):
        from mcp_linx.audit import AuditLogger

        audit = AuditLogger.from_config({})
        assert audit.enabled is False

    def test_from_config_enabled(self, tmp_path):
        from mcp_linx.audit import AuditLogger

        audit = AuditLogger.from_config(
            {"telemetry": {"audit_log": True, "audit_log_file": str(tmp_path / "a.log")}}
        )
        assert audit.enabled is True


class TestRateLimiter:
    def test_allows_within_limit(self):
        from mcp_linx.ratelimit import RateLimiter

        limiter = RateLimiter(max_calls=3, window_seconds=60)
        assert limiter.check("t1") is True
        assert limiter.check("t1") is True
        assert limiter.check("t1") is True

    def test_blocks_after_limit(self):
        from mcp_linx.ratelimit import RateLimiter
        from mcp_linx.security import SecurityError

        limiter = RateLimiter(max_calls=2, window_seconds=60)
        assert limiter.check("t1") is True
        assert limiter.check("t1") is True
        assert limiter.check("t1") is False

    def test_enforce_raises(self):
        from mcp_linx.ratelimit import RateLimiter
        from mcp_linx.security import SecurityError

        limiter = RateLimiter(max_calls=1, window_seconds=60)
        limiter.enforce("t1")  # ok
        with pytest.raises(SecurityError):
            limiter.enforce("t1")

    def test_per_key_independent(self):
        from mcp_linx.ratelimit import RateLimiter

        limiter = RateLimiter(max_calls=1, window_seconds=60)
        limiter.check("a")
        assert limiter.check("b") is True

    def test_window_expiry(self):
        from mcp_linx.ratelimit import RateLimiter

        limiter = RateLimiter(max_calls=1, window_seconds=1)
        limiter.check("t1")
        # принудительно старим запись
        import time

        with limiter._lock:
            limiter._calls["t1"][0] = time.monotonic() - 5
        assert limiter.check("t1") is True  # окно истекло, можно снова