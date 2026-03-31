"""
Tests for dlab.config module.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from dlab.config import (
    load_config_yaml,
    load_dpack_config,
    validate_config_structure,
)


class TestValidateConfigStructure:
    """Tests for validate_config_structure function."""

    def test_valid_structure(self, dpack_config_dir: Path) -> None:
        """Valid config directory should pass validation."""
        validate_config_structure(str(dpack_config_dir))

    def test_missing_directory(self, tmp_path: Path) -> None:
        """Non-existent directory should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            validate_config_structure(str(tmp_path / "nonexistent"))

    def test_not_a_directory(self, tmp_path: Path) -> None:
        """File instead of directory should raise ValueError."""
        file_path: Path = tmp_path / "not_a_dir"
        file_path.write_text("content")

        with pytest.raises(ValueError, match="not a directory"):
            validate_config_structure(str(file_path))

    def test_missing_docker_dir(self, tmp_path: Path) -> None:
        """Missing docker/ directory should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "opencode").mkdir()
        (dpack / "config.yaml").write_text("name: test\n")

        with pytest.raises(ValueError, match="Missing required directory: docker"):
            validate_config_structure(str(dpack))

    def test_missing_opencode_dir(self, tmp_path: Path) -> None:
        """Missing opencode/ directory should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "docker").mkdir()
        (dpack / "config.yaml").write_text("name: test\n")

        with pytest.raises(ValueError, match="Missing required directory: opencode"):
            validate_config_structure(str(dpack))

    def test_missing_config_yaml(self, tmp_path: Path) -> None:
        """Missing config.yaml should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "docker").mkdir()
        (dpack / "opencode").mkdir()

        with pytest.raises(ValueError, match="Missing required file: config.yaml"):
            validate_config_structure(str(dpack))


class TestLoadConfigYaml:
    """Tests for load_config_yaml function."""

    def test_valid_config(self, dpack_config_dir: Path) -> None:
        """Valid config.yaml should load correctly."""
        config: dict[str, Any] = load_config_yaml(str(dpack_config_dir))

        assert config["name"] == "test-dpack"
        assert config["description"] == "Test decision-pack for unit tests"
        assert config["docker_image_name"] == "test-dpack-img"
        assert config["default_model"] == "anthropic/claude-sonnet-4-0"

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """Invalid YAML should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "config.yaml").write_text("name: [invalid yaml\n")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config_yaml(str(dpack))

    def test_not_a_mapping(self, tmp_path: Path) -> None:
        """YAML list instead of mapping should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "config.yaml").write_text("- item1\n- item2\n")

        with pytest.raises(ValueError, match="must contain a YAML mapping"):
            load_config_yaml(str(dpack))

    def test_missing_required_keys(self, tmp_path: Path) -> None:
        """Missing required keys should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "config.yaml").write_text("name: test\n")

        with pytest.raises(ValueError, match="missing required keys"):
            load_config_yaml(str(dpack))


class TestLoadDpackConfig:
    """Tests for load_dpack_config function."""

    def test_full_load(self, dpack_config_dir: Path) -> None:
        """Full config load should include config_dir."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))

        assert config["name"] == "test-dpack"
        assert config["config_dir"] == str(dpack_config_dir.resolve())

    def test_resolves_relative_path(self, dpack_config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Relative paths should be resolved to absolute."""
        monkeypatch.chdir(dpack_config_dir.parent)

        config: dict[str, Any] = load_dpack_config("test-dpack")

        assert Path(config["config_dir"]).is_absolute()

    def test_default_opencode_version(self, dpack_config_dir: Path) -> None:
        """Should default opencode_version to 'latest' if not specified."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))

        assert config["opencode_version"] == "latest"

    def test_custom_opencode_version(self, tmp_path: Path) -> None:
        """Should use opencode_version from config if specified."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "docker").mkdir()
        (dpack / "opencode").mkdir()

        config_content: dict[str, Any] = {
            "name": "test",
            "description": "test",
            "docker_image_name": "test-img",
            "default_model": "anthropic/claude-sonnet-4-0",
            "opencode_version": "1.1.25",
        }
        with open(dpack / "config.yaml", "w") as f:
            yaml.dump(config_content, f)

        config: dict[str, Any] = load_dpack_config(str(dpack))

        assert config["opencode_version"] == "1.1.25"


def _make_dpack_dir(tmp_path: Path, hooks_yaml: str = "") -> Path:
    """Helper to create a decision-pack dir with optional hooks in config.yaml."""
    dpack: Path = tmp_path / "dpack"
    dpack.mkdir()
    (dpack / "docker").mkdir()
    (dpack / "opencode").mkdir()

    config_yaml: str = (
        "name: test\n"
        "description: test\n"
        "docker_image_name: test-img\n"
        "default_model: anthropic/claude-sonnet-4-0\n"
    )
    if hooks_yaml:
        config_yaml += hooks_yaml
    (dpack / "config.yaml").write_text(config_yaml)

    return dpack


class TestHooksNormalization:
    """Tests for hooks normalization in load_dpack_config."""

    def test_no_hooks(self, tmp_path: Path) -> None:
        """Config without hooks key should default to empty lists."""
        dpack: Path = _make_dpack_dir(tmp_path)
        config: dict[str, Any] = load_dpack_config(str(dpack))

        assert config["hooks"] == {"pre-run": [], "post-run": []}

    def test_hooks_string_to_list(self, tmp_path: Path) -> None:
        """String value should be normalized to single-element list."""
        dpack: Path = _make_dpack_dir(tmp_path, "hooks:\n  pre-run: script.sh\n")
        config: dict[str, Any] = load_dpack_config(str(dpack))

        assert config["hooks"]["pre-run"] == ["script.sh"]
        assert config["hooks"]["post-run"] == []

    def test_hooks_list_unchanged(self, tmp_path: Path) -> None:
        """List value should remain unchanged."""
        dpack: Path = _make_dpack_dir(
            tmp_path, "hooks:\n  pre-run:\n    - a.sh\n    - b.sh\n"
        )
        config: dict[str, Any] = load_dpack_config(str(dpack))

        assert config["hooks"]["pre-run"] == ["a.sh", "b.sh"]

    def test_hooks_invalid_type_ignored(self, tmp_path: Path) -> None:
        """Non-dict hooks value should default to empty."""
        dpack: Path = _make_dpack_dir(tmp_path, "hooks: not_a_dict\n")
        config: dict[str, Any] = load_dpack_config(str(dpack))

        assert config["hooks"] == {"pre-run": [], "post-run": []}

    def test_hooks_mixed(self, tmp_path: Path) -> None:
        """Mixed string and list should both be normalized."""
        dpack: Path = _make_dpack_dir(
            tmp_path,
            "hooks:\n  pre-run: one.sh\n  post-run:\n    - a.sh\n    - b.sh\n",
        )
        config: dict[str, Any] = load_dpack_config(str(dpack))

        assert config["hooks"]["pre-run"] == ["one.sh"]
        assert config["hooks"]["post-run"] == ["a.sh", "b.sh"]
