"""Tests for the suite loader.

Validates: YAML loading, schema validation, hash stability, multi-language support.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from driftwatch.schema.models import Language
from driftwatch.suites.loader import load_all_suites, load_suite


class TestLoadSuite:
    def test_loads_single_scenario(self, tmp_suites_dir: Path) -> None:
        manifest = load_suite(tmp_suites_dir / "attacks_v1")
        assert manifest.name == "attacks_v1"
        assert len(manifest.scenarios) == 1
        assert manifest.scenarios[0].id == "atk_refund_review_en_01"

    def test_scenario_fields_parsed(self, tmp_suites_dir: Path) -> None:
        manifest = load_suite(tmp_suites_dir / "attacks_v1")
        s = manifest.scenarios[0]
        assert s.language == Language.EN
        assert s.injection is not None
        assert s.injection.tool == "read_reviews"
        assert s.goal.tool_called is not None
        assert s.goal.tool_called["name"] == "issue_refund"

    def test_hash_is_sha256_hex(self, tmp_suites_dir: Path) -> None:
        manifest = load_suite(tmp_suites_dir / "attacks_v1")
        assert len(manifest.suite_hash) == 64
        assert all(c in "0123456789abcdef" for c in manifest.suite_hash)

    def test_hash_is_stable(self, tmp_suites_dir: Path) -> None:
        """Hash must be the same on repeated loads (AGENTS.md testing requirements)."""
        h1 = load_suite(tmp_suites_dir / "attacks_v1").suite_hash
        h2 = load_suite(tmp_suites_dir / "attacks_v1").suite_hash
        assert h1 == h2

    def test_hash_changes_on_content_change(self, tmp_suites_dir: Path) -> None:
        h_before = load_suite(tmp_suites_dir / "attacks_v1").suite_hash

        # Modify a payload file
        payload = tmp_suites_dir / "attacks_v1" / "payloads" / "refund_override_en_01.txt"
        payload.write_text("MODIFIED PAYLOAD", encoding="utf-8")

        h_after = load_suite(tmp_suites_dir / "attacks_v1").suite_hash
        assert h_before != h_after

    def test_nonexistent_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_suite(tmp_path / "nonexistent")

    def test_empty_dir_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty_suite"
        empty.mkdir()
        with pytest.raises(ValueError, match="No YAML files"):
            load_suite(empty)


class TestLoadMultiLanguageSuite:
    def test_loads_telugu_and_tenglish(self, tmp_telugu_suite: Path) -> None:
        manifest = load_suite(tmp_telugu_suite / "attacks_v1")
        assert len(manifest.scenarios) == 2

        langs = {s.language for s in manifest.scenarios}
        assert Language.TE in langs
        assert Language.TE_EN in langs

    def test_telugu_unicode_preserved(self, tmp_telugu_suite: Path) -> None:
        manifest = load_suite(tmp_telugu_suite / "attacks_v1")
        te_scenario = next(s for s in manifest.scenarios if s.language == Language.TE)
        # Verify Telugu script characters are preserved
        assert "ఆర్డర్" in te_scenario.user_turns[0]

    def test_tenglish_channel(self, tmp_telugu_suite: Path) -> None:
        manifest = load_suite(tmp_telugu_suite / "attacks_v1")
        teen_scenario = next(s for s in manifest.scenarios if s.language == Language.TE_EN)
        from driftwatch.schema.models import Channel

        assert teen_scenario.channel == Channel.TOOL_DESCRIPTION


class TestLoadAllSuites:
    def test_loads_multiple_suites(self, tmp_suites_multi: Path) -> None:
        manifests = load_all_suites(tmp_suites_multi)
        assert "attacks_v1" in manifests
        assert "control" in manifests
        assert len(manifests) == 2

    def test_nonexistent_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_all_suites(tmp_path / "no_such_dir")


class TestHashStabilityAcrossFileOrderings:
    """Hash must be stable regardless of file system ordering (AGENTS.md testing req)."""

    def test_hash_independent_of_creation_order(self, tmp_path: Path) -> None:
        suite_dir = tmp_path / "suite_a"
        suite_dir.mkdir()

        # Create files in one order
        (suite_dir / "z_last.yaml").write_text(
            dedent("""\
            id: z_scenario
            suite: suite_a
            language: en
            channel: tool_output
            world: worlds/w.yaml
            user_turns: ["z task"]
            goal:
              state_equals: {done: true}
        """),
            encoding="utf-8",
        )

        (suite_dir / "a_first.yaml").write_text(
            dedent("""\
            id: a_scenario
            suite: suite_a
            language: en
            channel: tool_output
            world: worlds/w.yaml
            user_turns: ["a task"]
            goal:
              state_equals: {done: true}
        """),
            encoding="utf-8",
        )

        h1 = load_suite(suite_dir).suite_hash

        # Create the same files in a fresh directory (different creation order)
        suite_dir2 = tmp_path / "suite_b"
        suite_dir2.mkdir()

        (suite_dir2 / "a_first.yaml").write_text(
            dedent("""\
            id: a_scenario
            suite: suite_a
            language: en
            channel: tool_output
            world: worlds/w.yaml
            user_turns: ["a task"]
            goal:
              state_equals: {done: true}
        """),
            encoding="utf-8",
        )

        (suite_dir2 / "z_last.yaml").write_text(
            dedent("""\
            id: z_scenario
            suite: suite_a
            language: en
            channel: tool_output
            world: worlds/w.yaml
            user_turns: ["z task"]
            goal:
              state_equals: {done: true}
        """),
            encoding="utf-8",
        )

        h2 = load_suite(suite_dir2).suite_hash
        assert h1 == h2, "Hash must be stable regardless of file creation order"
