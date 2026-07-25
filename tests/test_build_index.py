"""Tests for scripts/build_index.py — the v0 index-table generator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_index.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_index", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

INDEX_SKELETON = textwrap.dedent("""\
    # Index

    ## Accepted tools
    <!-- INDEX:ACCEPTED START -->
    _No accepted tools yet._
    <!-- INDEX:ACCEPTED END -->

    ## Under review
    <!-- INDEX:REVIEW START -->
    _Nothing under review._
    <!-- INDEX:REVIEW END -->
    """)


def setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    entries = tmp_path / "entries"
    entries.mkdir()
    index = tmp_path / "INDEX.md"
    index.write_text(INDEX_SKELETON, encoding="utf-8")
    return index, entries


def write_entry(entries: Path, name: str, **fields) -> None:
    lines = []
    for k, v in fields.items():
        if isinstance(v, list):
            v = "[" + ", ".join(v) + "]"
        lines.append(f"{k}: {v}")
    (entries / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_build(index: Path, entries: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--index", str(index),
         "--entries", str(entries), *extra],
        capture_output=True, text=True,
    )


def test_accepted_entry_is_listed_with_copyleft_and_doi(tmp_path):
    index, entries = setup_repo(tmp_path)
    write_entry(entries, "tool_a.yml", tool_name='"Tool A"', tier='"2"',
                license='"GPL-3.0-or-later"', verified_date='"2026-07-24"',
                doi='"10.5281/zenodo.123"',
                live_repo='"https://example.com/a"')
    proc = run_build(index, entries)
    assert proc.returncode == 0
    text = index.read_text(encoding="utf-8")
    accepted = text.split("INDEX:ACCEPTED START")[1].split("INDEX:ACCEPTED END")[0]
    assert "Tool A" in accepted
    assert "⚠ copyleft" in accepted           # D11 copyleft flag
    assert "10.5281/zenodo.123" in accepted    # DOI rendered
    # Accepted, so it must NOT be under review.
    review = text.split("INDEX:REVIEW START")[1].split("INDEX:REVIEW END")[0]
    assert "Tool A" not in review


def test_entry_without_verified_date_is_under_review(tmp_path):
    index, entries = setup_repo(tmp_path)
    write_entry(entries, "pending.yml", tool_name='"Pending Tool"', tier='"1"',
                license='"MIT"', verified_date='""',
                live_repo='"https://example.com/p"')
    proc = run_build(index, entries)
    assert proc.returncode == 0
    text = index.read_text(encoding="utf-8")
    review = text.split("INDEX:REVIEW START")[1].split("INDEX:REVIEW END")[0]
    assert "Pending Tool" in review
    accepted = text.split("INDEX:ACCEPTED START")[1].split("INDEX:ACCEPTED END")[0]
    assert "Pending Tool" not in accepted


def test_underscore_files_are_skipped(tmp_path):
    index, entries = setup_repo(tmp_path)
    write_entry(entries, "_TEMPLATE.yml", tool_name='"SHOULD NOT APPEAR"',
                tier='"1"', verified_date='"2026-01-01"')
    proc = run_build(index, entries)
    assert proc.returncode == 0
    assert "SHOULD NOT APPEAR" not in index.read_text(encoding="utf-8")


def test_empty_entries_render_placeholders(tmp_path):
    index, entries = setup_repo(tmp_path)
    proc = run_build(index, entries)
    assert proc.returncode == 0
    text = index.read_text(encoding="utf-8")
    assert "_No accepted tools yet._" in text
    assert "_Nothing under review._" in text


def test_check_flags_stale_and_does_not_write(tmp_path):
    index, entries = setup_repo(tmp_path)
    write_entry(entries, "tool_a.yml", tool_name='"Tool A"', tier='"1"',
                verified_date='"2026-07-24"', license='"MIT"')
    # Fresh skeleton is stale relative to the entry.
    before = index.read_text(encoding="utf-8")
    proc = run_build(index, entries, "--check")
    assert proc.returncode == 1
    assert index.read_text(encoding="utf-8") == before   # unchanged
    # After a real build, --check passes.
    assert run_build(index, entries).returncode == 0
    assert run_build(index, entries, "--check").returncode == 0


def test_resolve_index_prefers_marked_readme(tmp_path):
    """In the org `index` repo the page is README.md; here it is INDEX.md.
    Both must resolve without --index."""
    build_index = _load_module()
    assert build_index.resolve_index(tmp_path) is None      # neither present

    (tmp_path / "INDEX.md").write_text(INDEX_SKELETON, encoding="utf-8")
    assert build_index.resolve_index(tmp_path).name == "INDEX.md"

    # An unrelated README (no markers) must NOT win over the real index page.
    (tmp_path / "README.md").write_text("# Planning repo\n", encoding="utf-8")
    assert build_index.resolve_index(tmp_path).name == "INDEX.md"

    # Once README.md carries the markers it takes precedence.
    (tmp_path / "README.md").write_text(INDEX_SKELETON, encoding="utf-8")
    assert build_index.resolve_index(tmp_path).name == "README.md"


def test_build_is_deterministic(tmp_path):
    index, entries = setup_repo(tmp_path)
    write_entry(entries, "b.yml", tool_name='"Bravo"', tier='"2"',
                verified_date='"2026-07-24"', license='"Apache-2.0"')
    write_entry(entries, "a.yml", tool_name='"Alpha"', tier='"1"',
                verified_date='"2026-07-24"', license='"MIT"')
    run_build(index, entries)
    first = index.read_text(encoding="utf-8")
    run_build(index, entries)
    assert index.read_text(encoding="utf-8") == first
    # Sorted by tool_name: Alpha precedes Bravo.
    assert first.index("Alpha") < first.index("Bravo")
