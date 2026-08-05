"""
Tests for model-catalog freshness (issue #91) and opencode version pinning
(issue #92): the TTL-based background cache refresh, fatal-error diagnosis,
and the pinned opencode_version in generated decision-packs.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dlab.config import load_dpack_config
from dlab.create_dpack import (
    MODEL_CACHE_TTL_SECONDS,
    generate_dpack,
    refresh_model_cache_if_stale,
    resolve_latest_opencode_version,
)
from dlab.opencode_logparser import diagnose_fatal_error


class TestCacheRefresh:
    def test_skipped_when_cache_fresh(self, tmp_path: Path) -> None:
        """A cache younger than the TTL triggers no refresh."""
        cache: Path = tmp_path / "models.json"
        cache.write_text(json.dumps({"models": ["a/b"], "provider_envs": {}}))
        thread = refresh_model_cache_if_stale(
            cache_file=cache, attempt_file=tmp_path / "attempt",
        )
        assert thread is None

    def test_skipped_within_retry_window(self, tmp_path: Path) -> None:
        """A recent failed attempt suppresses retries even with a stale cache."""
        cache: Path = tmp_path / "models.json"
        cache.write_text(json.dumps({"models": [], "provider_envs": {}}))
        stale: float = time.time() - MODEL_CACHE_TTL_SECONDS - 60
        os.utime(cache, (stale, stale))
        attempt: Path = tmp_path / "attempt"
        attempt.touch()

        thread = refresh_model_cache_if_stale(
            cache_file=cache, attempt_file=attempt,
        )
        assert thread is None

    def test_stale_cache_refreshes_in_background(self, tmp_path: Path) -> None:
        """A stale cache spawns a refresh thread that rewrites it (network)."""
        cache: Path = tmp_path / "models.json"
        cache.write_text(json.dumps({"models": ["dead/model"], "provider_envs": {}}))
        stale: float = time.time() - MODEL_CACHE_TTL_SECONDS - 60
        os.utime(cache, (stale, stale))
        attempt: Path = tmp_path / "attempt"

        thread = refresh_model_cache_if_stale(
            cache_file=cache, attempt_file=attempt,
        )
        assert thread is not None
        assert attempt.exists()  # attempt recorded before the fetch
        thread.join(timeout=30)

        refreshed: dict[str, Any] = json.loads(cache.read_text())
        assert len(refreshed["models"]) > 100
        assert refreshed["provider_envs"]


class TestFatalErrorDiagnosis:
    def test_model_not_found_includes_model_id(self) -> None:
        log: str = (
            'error="ProviderModelNotFoundError: Model not found: '
            'anthropic/claude-sonnet-4-0. Did you mean..."'
        )
        diagnosis: str | None = diagnose_fatal_error(log)
        assert diagnosis is not None
        assert "anthropic/claude-sonnet-4-0" in diagnosis
        assert "default_model" in diagnosis

    def test_invalid_api_key(self) -> None:
        diagnosis: str | None = diagnose_fatal_error(
            '{"message":"invalid x-api-key","statusCode":401}'
        )
        assert diagnosis is not None
        assert "--env-file" in diagnosis

    def test_clean_log_yields_none(self) -> None:
        assert diagnose_fatal_error("all done, wrote report.md") is None


class TestOpencodeVersionPinning:
    def test_resolver_returns_version_or_latest(self) -> None:
        version: str = resolve_latest_opencode_version()
        assert version == "latest" or re.fullmatch(r"\d+\.\d+\.\d+", version), version

    def test_generated_pack_pins_opencode_version(self, tmp_path: Path) -> None:
        """generate_dpack writes a concrete opencode_version into config.yaml."""
        generate_dpack(tmp_path, {
            "name": "pin-test",
            "default_model": "anthropic/claude-sonnet-4-5",
        })
        config: dict[str, Any] = load_dpack_config(str(tmp_path / "pin-test"))
        assert config["opencode_version"] == resolve_latest_opencode_version()

    def test_explicit_opencode_version_wins(self, tmp_path: Path) -> None:
        """An explicit opencode_version in the config dict is written as-is."""
        generate_dpack(tmp_path, {
            "name": "pin-explicit",
            "default_model": "anthropic/claude-sonnet-4-5",
            "opencode_version": "1.2.10",
        })
        config: dict[str, Any] = load_dpack_config(str(tmp_path / "pin-explicit"))
        assert config["opencode_version"] == "1.2.10"
