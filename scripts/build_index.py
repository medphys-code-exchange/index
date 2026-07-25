#!/usr/bin/env python3
"""Build the index tables in the index page from per-submission entries/*.yml.

The index page carries two GENERATED tables — accepted tools and submissions
under review — rendered from the metadata records in entries/ (schema:
templates/submission_metadata.yml). This is the v0 index
(docs/org_standup.md item 5): plain Markdown, not a static site.

The page is README.md in the org `index` repo and INDEX.md in the planning
repo; with no --index the script picks whichever carries the generated-table
markers, so the same file works unmodified in both.

Status is derived from the data: an entry with a `verified_date` is accepted
and listed in the main table; an entry without one is under review.

Determinism: entries are sorted by tool_name, so output is byte-stable and
`--check` can gate CI (exit 1 if the page is stale).

Usage:
    python scripts/build_index.py                 # rewrite the page in place
    python scripts/build_index.py --check          # exit 1 if the page is stale
    python scripts/build_index.py --index P --entries D   # override paths

Exit codes: 0 = wrote / up-to-date, 1 = stale (--check) or error.

Requires: PyYAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

ACCEPTED_START = "<!-- INDEX:ACCEPTED START -->"
ACCEPTED_END = "<!-- INDEX:ACCEPTED END -->"
REVIEW_START = "<!-- INDEX:REVIEW START -->"
REVIEW_END = "<!-- INDEX:REVIEW END -->"

# The index page is README.md in the org `index` repo, INDEX.md here. Checked
# in order; the marker test avoids matching an unrelated README.
INDEX_CANDIDATES = ("README.md", "INDEX.md")

# License families flagged as copyleft on the index (D11).
COPYLEFT_PREFIXES = ("GPL-", "AGPL-", "LGPL-", "EUPL-", "MPL-")


def load_entries(entries_dir: Path) -> list[dict]:
    """Load entries/*.yml (skipping files whose name starts with '_'),
    sorted by tool_name for deterministic output."""
    entries = []
    for path in sorted(entries_dir.glob("*.yml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data["_file"] = path.name
        entries.append(data)
    entries.sort(key=lambda e: str(e.get("tool_name", "")).lower())
    return entries


def _s(value) -> str:
    """Render a scalar/list field as a compact table cell, escaping pipes."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v not in (None, ""))
    text = str(value).strip() if value not in (None, "") else ""
    return text.replace("|", r"\|") or "—"


def _license(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    if text.startswith(COPYLEFT_PREFIXES):
        return f"{text} ⚠ copyleft"
    return text


def _link(url: str, label: str = "link") -> str:
    url = str(url or "").strip()
    return f"[{label}]({url})" if url else "—"


def _doi(value) -> str:
    doi = str(value or "").strip()
    if not doi:
        return "—"
    if doi.startswith("http"):
        return f"[{doi}]({doi})"
    return f"[{doi}](https://doi.org/{doi})"


def is_accepted(entry: dict) -> bool:
    return bool(str(entry.get("verified_date", "")).strip())


def render_accepted(entries: list[dict]) -> str:
    rows = [e for e in entries if is_accepted(e)]
    if not rows:
        return "_No accepted tools yet._"
    header = ("| Tool | Tier | License | Category | Platform | Live | Frozen | "
              "DOI | Verified | Reviewers |\n"
              "|---|---|---|---|---|---|---|---|---|---|")
    lines = [header]
    for e in rows:
        pm = e.get("platform_matrix") or {}
        platform = ", ".join(
            p for p in (str(pm.get("runtime", "")).strip(),
                        str(pm.get("vendor", "")).strip()) if p) or "—"
        lines.append("| " + " | ".join([
            _s(e.get("tool_name")),
            f"Tier {_s(e.get('tier'))}",
            _license(e.get("license")),
            _s(e.get("category")),
            platform.replace("|", r"\|"),
            _link(e.get("live_repo"), "repo"),
            _link(e.get("frozen_fork"), "fork"),
            _doi(e.get("doi")),
            _s(e.get("verified_date")),
            _s(e.get("reviewers")),
        ]) + " |")
    return "\n".join(lines)


def render_review(entries: list[dict]) -> str:
    rows = [e for e in entries if not is_accepted(e)]
    if not rows:
        return "_Nothing under review._"
    header = ("| Tool | Tier (requested) | Live | Review |\n"
              "|---|---|---|---|")
    lines = [header]
    for e in rows:
        lines.append("| " + " | ".join([
            _s(e.get("tool_name")),
            f"Tier {_s(e.get('tier'))}",
            _link(e.get("live_repo"), "repo"),
            _link(e.get("review_issue"), "issue"),
        ]) + " |")
    return "\n".join(lines)


def resolve_index(repo: Path) -> Path | None:
    """Return the index page: the first candidate that exists AND carries the
    generated-table markers. Returns None if neither qualifies."""
    for name in INDEX_CANDIDATES:
        path = repo / name
        if not path.is_file():
            continue
        try:
            if ACCEPTED_START in path.read_text(encoding="utf-8"):
                return path
        except OSError:
            continue
    return None


def inject(text: str, start: str, end: str, block: str) -> str:
    if start not in text or end not in text:
        raise ValueError(f"markers {start!r}/{end!r} not found in index page")
    head, _, rest = text.partition(start)
    _, _, tail = rest.partition(end)
    return f"{head}{start}\n{block}\n{end}{tail}"


def build(index_path: Path, entries_dir: Path) -> str:
    entries = load_entries(entries_dir)
    text = index_path.read_text(encoding="utf-8")
    text = inject(text, ACCEPTED_START, ACCEPTED_END, render_accepted(entries))
    text = inject(text, REVIEW_START, REVIEW_END, render_review(entries))
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", type=Path, default=None,
                    help="index page (default: README.md or INDEX.md, "
                         "whichever carries the generated-table markers)")
    ap.add_argument("--entries", type=Path, default=REPO / "entries")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the index page is out of date (do not write)")
    args = ap.parse_args()

    if args.index is None:
        args.index = resolve_index(REPO)
        if args.index is None:
            print("error: no index page found — expected one of "
                  f"{', '.join(INDEX_CANDIDATES)} in {REPO} carrying the "
                  f"{ACCEPTED_START} marker", file=sys.stderr)
            return 1

    if not args.index.exists():
        print(f"error: index not found: {args.index}", file=sys.stderr)
        return 1
    if not args.entries.is_dir():
        print(f"error: entries dir not found: {args.entries}", file=sys.stderr)
        return 1

    try:
        new_text = build(args.index, args.entries)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    current = args.index.read_text(encoding="utf-8")
    if args.check:
        if current != new_text:
            print(f"{args.index.name} is stale — run: "
                  "python scripts/build_index.py", file=sys.stderr)
            return 1
        print(f"{args.index.name} is up to date.")
        return 0

    if current != new_text:
        args.index.write_text(new_text, encoding="utf-8", newline="\n")
        print(f"Wrote {args.index.name}.")
    else:
        print(f"{args.index.name} already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
