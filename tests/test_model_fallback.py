"""Tests for dlab.model_fallback module."""

import textwrap
from pathlib import Path

from dlab.model_fallback import (
    apply_model_fallback,
    find_model_strings,
    get_available_providers,
    parse_env_file,
    preflight_check,
    process_opencode_dir,
)


class TestParseEnvFile:
    """Tests for parse_env_file()."""

    def test_none_returns_empty(self) -> None:
        assert parse_env_file(None) == {}

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert parse_env_file(str(tmp_path / "nonexistent.env")) == {}

    def test_basic_parsing(self, tmp_path: Path) -> None:
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-ant-123\nOPENAI_API_KEY=sk-456\n")
        result: dict[str, str] = parse_env_file(str(env_file))
        assert result == {
            "ANTHROPIC_API_KEY": "sk-ant-123",
            "OPENAI_API_KEY": "sk-456",
        }

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file: Path = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=value\n  \n# another\n")
        result: dict[str, str] = parse_env_file(str(env_file))
        assert result == {"KEY": "value"}

    def test_strips_quotes(self, tmp_path: Path) -> None:
        env_file: Path = tmp_path / ".env"
        env_file.write_text("A='quoted'\nB=\"double\"\nC=plain\n")
        result: dict[str, str] = parse_env_file(str(env_file))
        assert result == {"A": "quoted", "B": "double", "C": "plain"}

    def test_empty_value(self, tmp_path: Path) -> None:
        env_file: Path = tmp_path / ".env"
        env_file.write_text("KEY=\n")
        result: dict[str, str] = parse_env_file(str(env_file))
        assert result == {"KEY": ""}


class TestGetAvailableProviders:
    """Tests for get_available_providers()."""

    def test_empty_env(self) -> None:
        assert get_available_providers({}) == set()

    def test_anthropic_available(self) -> None:
        env: dict[str, str] = {"ANTHROPIC_API_KEY": "sk-123"}
        result: set[str] = get_available_providers(env)
        assert "anthropic" in result

    def test_multiple_providers(self) -> None:
        env: dict[str, str] = {
            "ANTHROPIC_API_KEY": "sk-123",
            "OPENAI_API_KEY": "sk-456",
        }
        result: set[str] = get_available_providers(env)
        assert result == {"anthropic", "openai"}

    def test_empty_value_not_counted(self) -> None:
        env: dict[str, str] = {"ANTHROPIC_API_KEY": ""}
        result: set[str] = get_available_providers(env)
        assert "anthropic" not in result

    def test_unknown_key_ignored(self) -> None:
        env: dict[str, str] = {"RANDOM_KEY": "value"}
        result: set[str] = get_available_providers(env)
        assert result == set()


class TestFindModelStrings:
    """Tests for find_model_strings()."""

    def test_finds_models_in_yaml(self) -> None:
        text: str = 'default_model: "anthropic/claude-sonnet-4-5"\n'
        result: list[str] = find_model_strings(text)
        assert result == ["anthropic/claude-sonnet-4-5"]

    def test_finds_multiple(self) -> None:
        text: str = textwrap.dedent("""\
            default_model: "anthropic/claude-opus-4-5"
            summarizer_model: "google/gemini-2.5-pro"
        """)
        result: list[str] = find_model_strings(text)
        assert "anthropic/claude-opus-4-5" in result
        assert "google/gemini-2.5-pro" in result

    def test_deduplicates(self) -> None:
        text: str = '"anthropic/claude-sonnet-4-0"\n"anthropic/claude-sonnet-4-0"\n'
        result: list[str] = find_model_strings(text)
        assert result == ["anthropic/claude-sonnet-4-0"]

    def test_ignores_non_provider_paths(self) -> None:
        text: str = "some/random/path\nfoo/bar\n"
        result: list[str] = find_model_strings(text)
        assert result == []

    def test_finds_in_markdown_body(self) -> None:
        text: str = textwrap.dedent("""\
            ---
            mode: primary
            ---
            Use "models": ["anthropic/claude-opus-4-5", "google/gemini-2.5-pro"]
        """)
        result: list[str] = find_model_strings(text)
        assert "anthropic/claude-opus-4-5" in result
        assert "google/gemini-2.5-pro" in result


class TestPreflightCheck:
    """Tests for preflight_check()."""

    def _make_dpack(self, tmp_path: Path, agent_content: str) -> Path:
        """Helper to create a minimal dpack with an agent file."""
        dpack: Path = tmp_path / "dpack"
        agents_dir: Path = dpack / "opencode" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "orchestrator.md").write_text(agent_content)
        return dpack

    def test_orchestrator_key_missing_is_error(self, tmp_path: Path) -> None:
        dpack: Path = self._make_dpack(tmp_path, "Use anthropic/claude-opus-4-0")
        env_file: Path = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), str(env_file),
        )
        assert len(errors) == 1
        assert "ANTHROPIC_API_KEY" in errors[0]
        assert "anthropic/claude-opus-4-0" in errors[0]

    def test_orchestrator_key_present_no_error(self, tmp_path: Path) -> None:
        dpack: Path = self._make_dpack(tmp_path, "Use anthropic/claude-opus-4-0")
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), str(env_file),
        )
        assert errors == []

    def test_unknown_model_is_error_with_suggestion(self, tmp_path: Path) -> None:
        dpack: Path = self._make_dpack(tmp_path, 'model: "anthropic/claude-sonet-4"')
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), str(env_file),
        )
        assert any("anthropic/claude-sonet-4" in e for e in errors)
        assert any("did you mean" in e for e in errors)

    def test_unknown_orchestrator_model_is_error(self, tmp_path: Path) -> None:
        dpack: Path = self._make_dpack(tmp_path, "some content")
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-sonet-4", str(dpack), str(env_file),
        )
        assert len(errors) == 1
        assert "anthropic/claude-sonet-4" in errors[0]
        assert "did you mean" in errors[0]

    def test_missing_agent_key_is_warning_with_hint(self, tmp_path: Path) -> None:
        dpack: Path = tmp_path / "dpack"
        pa_dir: Path = dpack / "opencode" / "parallel_agents"
        pa_dir.mkdir(parents=True)
        (pa_dir / "poet.yaml").write_text(
            'default_model: "google/gemini-2.0-flash"\n'
        )
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), str(env_file),
        )
        assert errors == []
        assert len(warnings) >= 1
        assert any("google/gemini-2.0-flash" in w for w in warnings)
        assert any("GOOGLE_GENERATIVE_AI_API_KEY" in w for w in warnings)
        assert any("anthropic/claude-opus-4-0" in w for w in warnings)

    def test_all_keys_present_no_warnings(self, tmp_path: Path) -> None:
        dpack: Path = tmp_path / "dpack"
        pa_dir: Path = dpack / "opencode" / "parallel_agents"
        pa_dir.mkdir(parents=True)
        (pa_dir / "agent.yaml").write_text(
            'default_model: "anthropic/claude-sonnet-4-0"\n'
        )
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), str(env_file),
        )
        assert errors == []
        assert warnings == []

    def test_no_env_file_orchestrator_error(self, tmp_path: Path) -> None:
        dpack: Path = self._make_dpack(tmp_path, "Use anthropic/claude-opus-4-0")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), None,
        )
        assert len(errors) == 1
        assert "ANTHROPIC_API_KEY" in errors[0]

    def test_deduplicates_warnings(self, tmp_path: Path) -> None:
        """Same model appearing in multiple files should produce one warning."""
        dpack: Path = tmp_path / "dpack"
        pa_dir: Path = dpack / "opencode" / "parallel_agents"
        pa_dir.mkdir(parents=True)
        agents_dir: Path = dpack / "opencode" / "agents"
        agents_dir.mkdir(parents=True)
        (pa_dir / "a.yaml").write_text('default_model: "google/gemini-2.0-flash"\n')
        (agents_dir / "b.md").write_text("Use google/gemini-2.0-flash\n")
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        errors, warnings = preflight_check(
            "anthropic/claude-opus-4-0", str(dpack), str(env_file),
        )
        # Only one warning for google/gemini-2.0-flash, not two
        google_warnings: list[str] = [
            w for w in warnings if "google/gemini-2.0-flash" in w
        ]
        assert len(google_warnings) == 1


class TestApplyModelFallback:
    """Tests for apply_model_fallback()."""

    def test_no_unavailable_providers(self) -> None:
        text: str = 'default_model: "anthropic/claude-sonnet-4-0"\n'
        new_text, replacements = apply_model_fallback(
            text, "anthropic/claude-opus-4-0", set(),
        )
        assert new_text == text
        assert replacements == []

    def test_replaces_unavailable_provider(self) -> None:
        text: str = 'default_model: "google/gemini-2.5-pro"\n'
        new_text, replacements = apply_model_fallback(
            text, "anthropic/claude-opus-4-0", {"google"},
        )
        assert "anthropic/claude-opus-4-0" in new_text
        assert "google/gemini-2.5-pro" not in new_text
        assert len(replacements) == 1

    def test_preserves_available_provider(self) -> None:
        text: str = textwrap.dedent("""\
            default_model: "anthropic/claude-sonnet-4-0"
            summarizer_model: "google/gemini-2.5-pro"
        """)
        new_text, replacements = apply_model_fallback(
            text, "anthropic/claude-opus-4-0", {"google"},
        )
        assert "anthropic/claude-sonnet-4-0" in new_text
        assert "anthropic/claude-opus-4-0" in new_text
        assert len(replacements) == 1

    def test_replaces_multiple_occurrences(self) -> None:
        text: str = textwrap.dedent("""\
            default_model: "google/gemini-2.5-pro"
            summarizer_model: "google/gemini-2.0-flash"
        """)
        new_text, replacements = apply_model_fallback(
            text, "anthropic/claude-opus-4-0", {"google"},
        )
        assert "google/" not in new_text
        assert len(replacements) == 2

    def test_replaces_in_markdown_body(self) -> None:
        text: str = 'Use model "google/gemini-2.5-pro" for analysis.\n'
        new_text, replacements = apply_model_fallback(
            text, "anthropic/claude-opus-4-0", {"google"},
        )
        assert 'Use model "anthropic/claude-opus-4-0" for analysis.\n' == new_text
        assert len(replacements) == 1


class TestProcessOpencodeDir:
    """Tests for process_opencode_dir()."""

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        result: list[str] = process_opencode_dir(
            str(tmp_path / "nope"), "anthropic/claude-opus-4-0", None,
        )
        assert result == []

    def test_no_fallback_when_all_keys_present(self, tmp_path: Path) -> None:
        opencode_dir: Path = tmp_path / ".opencode"
        pa_dir: Path = opencode_dir / "parallel_agents"
        pa_dir.mkdir(parents=True)
        (pa_dir / "agent.yaml").write_text(
            'default_model: "anthropic/claude-sonnet-4-0"\n'
        )
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        result: list[str] = process_opencode_dir(
            str(opencode_dir), "anthropic/claude-opus-4-0", str(env_file),
        )
        content: str = (pa_dir / "agent.yaml").read_text()
        assert "anthropic/claude-sonnet-4-0" in content
        assert result == []

    def test_fallback_replaces_in_yaml(self, tmp_path: Path) -> None:
        opencode_dir: Path = tmp_path / ".opencode"
        pa_dir: Path = opencode_dir / "parallel_agents"
        pa_dir.mkdir(parents=True)
        (pa_dir / "agent.yaml").write_text(
            'default_model: "google/gemini-2.5-pro"\n'
            'summarizer_model: "google/gemini-2.0-flash"\n'
        )
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        result: list[str] = process_opencode_dir(
            str(opencode_dir), "anthropic/claude-opus-4-0", str(env_file),
        )
        content: str = (pa_dir / "agent.yaml").read_text()
        assert "google/" not in content
        assert "anthropic/claude-opus-4-0" in content
        assert any("-> " in msg for msg in result)

    def test_fallback_replaces_in_markdown(self, tmp_path: Path) -> None:
        opencode_dir: Path = tmp_path / ".opencode"
        agents_dir: Path = opencode_dir / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "orchestrator.md").write_text(textwrap.dedent("""\
            ---
            mode: primary
            ---
            Use "models": ["google/gemini-2.5-pro"]
        """))
        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        result: list[str] = process_opencode_dir(
            str(opencode_dir), "anthropic/claude-opus-4-0", str(env_file),
        )
        content: str = (agents_dir / "orchestrator.md").read_text()
        assert "google/" not in content
        assert "anthropic/claude-opus-4-0" in content

    def test_skips_when_orchestrator_key_missing(self, tmp_path: Path) -> None:
        opencode_dir: Path = tmp_path / ".opencode"
        opencode_dir.mkdir(parents=True)
        env_file: Path = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-123\n")

        result: list[str] = process_opencode_dir(
            str(opencode_dir), "anthropic/claude-opus-4-0", str(env_file),
        )
        assert result == []

    def test_mixed_yaml_and_md(self, tmp_path: Path) -> None:
        opencode_dir: Path = tmp_path / ".opencode"
        pa_dir: Path = opencode_dir / "parallel_agents"
        pa_dir.mkdir(parents=True)
        agents_dir: Path = opencode_dir / "agents"
        agents_dir.mkdir(parents=True)

        (pa_dir / "modeler.yaml").write_text(textwrap.dedent("""\
            default_model: "google/gemini-2.5-pro"
            summarizer_model: "google/gemini-2.0-flash"
            summarizer_prompt: |
              Compare the results from all instances.
        """))
        (agents_dir / "orchestrator.md").write_text(textwrap.dedent("""\
            ---
            mode: primary
            ---
            Call parallel-agents with model google/gemini-2.5-pro
        """))

        env_file: Path = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-123\n")

        result: list[str] = process_opencode_dir(
            str(opencode_dir), "anthropic/claude-opus-4-0", str(env_file),
        )
        yaml_content: str = (pa_dir / "modeler.yaml").read_text()
        md_content: str = (agents_dir / "orchestrator.md").read_text()
        assert "google/" not in yaml_content
        assert "google/" not in md_content
        assert yaml_content.count("anthropic/claude-opus-4-0") == 2
        assert md_content.count("anthropic/claude-opus-4-0") == 1
