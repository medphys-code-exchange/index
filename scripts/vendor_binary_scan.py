#!/usr/bin/env python3
"""Vendor-binary scanner for code-index submissions.

Enforces the hard rule: no vendor binaries are ever committed. Detects:
  1. Known vendor assembly names (Varian ESAPI, RayStation, Elekta, Philips,
     MIM) anywhere in the tree, at ANY extension — renaming a vendor DLL to
     .bak/.old or stripping its extension does not evade detection. A
     clearly-text file merely carrying a vendor name in its filename (e.g.
     raystation_export.py — legitimate, in-scope script naming) is reported
     as an informational note only and does not affect the exit code.
  2. Any committed binary artifact (.dll/.exe/.pdb/.msi/...) not on the
     allowlist — submissions ship source, not binaries.
  3. Archives (.zip/.gz/.tgz/.tar/.7z/.rar/...): always a hard fail — an
     archive may conceal binaries; unpack or remove. Entry NAMES of zip/tar
     archives are enumerated (never extracted) so vendor assemblies hiding
     inside are called out by name. Exception: .nii.gz is compressed
     single-image data, allowlisted like bare .nii.
  4. bin/ and obj/ directories (the classic accidental ESAPI commit),
     matched case-insensitively and only BELOW the scan root. Binary
     content there is a hard fail; text-only content is flagged for review
     (Unix script-dir convention).
  5. Files that cannot be read at all — flagged for review (fail closed).

Exit codes: 0 = clean or informational notes only, 1 = hard_fail or review
findings (the output distinguishes them), 2 = usage/environment error.

Usage:
    python vendor_binary_scan.py <path> [--json]

<path> may be a directory (scanned recursively) or a single file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

# Filename patterns for known vendor assemblies. Case-insensitive and
# extension-agnostic: matched against the whole filename with re.search so
# 'VMS.TPS.Common.Model.API.dll.bak' or an extensionless copy still hits.
VENDOR_PATTERNS = [
    ("Varian ESAPI", re.compile(r"(?i)vms\.tps\.")),
    ("Varian", re.compile(r"(?i)^vms\.")),
    ("Varian", re.compile(r"(?i)^varian")),
    ("RaySearch/RayStation", re.compile(r"(?i)raystation")),
    ("RaySearch", re.compile(r"(?i)raysearch")),
    ("Elekta", re.compile(r"(?i)^(elekta|monaco|mosaiq)")),
    ("Philips Pinnacle", re.compile(r"(?i)^pinnacle")),
    ("MIM", re.compile(r"(?i)^mim(software)?\.")),
]

# Binary extensions disallowed in submissions (source-only policy).
BINARY_EXTENSIONS = {
    ".dll", ".exe", ".pdb", ".msi", ".so", ".dylib", ".pyd", ".lib",
    ".obj", ".o", ".a", ".jar", ".class", ".nupkg",
}

# Extensions that are binary but legitimately shippable (example data, docs).
# NOTE: archives (.zip/.gz/...) are deliberately NOT allowlisted — they can
# conceal binaries and are always a hard fail (ruling R-7).
ALLOWLIST_EXTENSIONS = {
    ".dcm", ".dicom", ".nii", ".npz", ".npy", ".png", ".jpg", ".jpeg",
    ".gif", ".pdf", ".mhd", ".mha", ".raw",
}

ARCHIVE_EXTENSIONS = {".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".bz2",
                      ".xz"}

# Extensions treated as clearly-text when deciding vendor-name severity.
TEXT_EXTENSIONS = {
    ".py", ".cs", ".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".xml",
    ".ipynb", ".m", ".r", ".jl", ".toml", ".cfg", ".ini", ".log", ".rst",
    ".sh", ".ps1", ".bat", ".html", ".css", ".js",
}

# Directory-name matching is case-insensitive and applies only to path
# components BELOW the scan root.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
BUILD_DIRS = {"bin", "obj"}


def rel_dir_parts(path: Path, root: Path) -> tuple[str, ...]:
    """Lower-cased directory components of path below root (excludes the
    filename itself). An ancestor directory above the scan root never
    participates in skip/build-dir matching."""
    try:
        rel = path.relative_to(root)
    except ValueError:  # pragma: no cover - rglob always yields sub-paths
        rel = path
    return tuple(part.lower() for part in rel.parts[:-1])


def probe_bytes(path: Path, probe: int = 8192) -> bytes | None:
    """First `probe` bytes of the file, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            return f.read(probe)
    except OSError:
        return None


def vendor_match(name: str) -> str | None:
    for vendor, pat in VENDOR_PATTERNS:
        if pat.search(name):
            return vendor
    return None


def binary_suggesting_name(name: str) -> bool:
    """True if the filename itself suggests binary content, at any position:
    'x.dll', 'x.dll.bak', 'x.exe.old', etc."""
    lname = name.lower()
    ext = Path(name).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True
    return any(hint + "." in lname or lname.endswith(hint)
               for hint in BINARY_EXTENSIONS)


def archive_entry_names(path: Path) -> list[str]:
    """Cheaply enumerate entry names of a zip/tar archive (never extracts).
    Returns [] if the archive cannot be enumerated."""
    try:
        if zipfile.is_zipfile(str(path)):
            with zipfile.ZipFile(str(path)) as zf:
                return zf.namelist()
        if tarfile.is_tarfile(str(path)):
            with tarfile.open(str(path)) as tf:
                return tf.getnames()
    except Exception:
        pass
    return []


def scan_one(path: Path, root: Path) -> list[dict]:
    """Scan a single file; root is used only for build-dir matching."""
    name = path.name
    ext = path.suffix.lower()
    dir_parts = rel_dir_parts(path, root)
    in_build_dir = any(part in BUILD_DIRS for part in dir_parts)

    chunk = probe_bytes(path)
    if chunk is None:
        # Fail closed: a file we cannot read cannot be cleared.
        return [{
            "file": str(path),
            "kind": "unreadable",
            "severity": "review",
            "message": "file could not be read - unscanned (fail closed)",
        }]
    has_binary_content = bool(chunk) and b"\x00" in chunk

    vendor = vendor_match(name)
    if vendor is not None:
        clearly_text = (ext in TEXT_EXTENSIONS and not has_binary_content)
        if clearly_text and not binary_suggesting_name(name):
            # Legitimate in-scope naming (raystation_export.py etc.):
            # informational only, never gates CI.
            return [{
                "file": str(path),
                "kind": "vendor_name",
                "vendor": vendor,
                "severity": "info",
                "message": ("text file carries a vendor name - "
                            "verify no vendor code is included"),
            }]
        return [{
            "file": str(path),
            "kind": "vendor_binary",
            "vendor": vendor,
            "severity": "hard_fail",
            "message": ("vendor assembly detected (extension-agnostic match)"
                        " - vendor binaries are never committed"),
        }]

    # .nii.gz is compressed single-image data, not a container archive —
    # allowlisted like bare .nii.
    if name.lower().endswith(".nii.gz"):
        return []

    if ext in ARCHIVE_EXTENSIONS:
        entries = archive_entry_names(path)
        vendor_entries = sorted({
            e for e in entries
            if vendor_match(Path(e).name) is not None
        })
        message = "archive may conceal binaries - unpack or remove"
        if vendor_entries:
            message += (" (contains vendor assembly entries: "
                        + ", ".join(vendor_entries) + ")")
        return [{
            "file": str(path),
            "kind": "archive",
            "severity": "hard_fail",
            "message": message,
        }]

    if in_build_dir:
        if has_binary_content or ext in BINARY_EXTENSIONS \
                or binary_suggesting_name(name):
            return [{
                "file": str(path),
                "kind": "build_output_committed",
                "severity": "hard_fail",
                "message": "binary content in bin/ or obj/ build directory",
            }]
        return [{
            "file": str(path),
            "kind": "build_dir_text",
            "severity": "review",
            "message": ("text file in bin/ or obj/ directory - verify this "
                        "is intentional (build output must not be "
                        "committed)"),
        }]

    if ext in BINARY_EXTENSIONS:
        return [{
            "file": str(path),
            "kind": "binary_artifact",
            "severity": "hard_fail",
            "message": "binary artifact - submissions ship source only",
        }]

    if ext not in ALLOWLIST_EXTENSIONS and has_binary_content:
        return [{
            "file": str(path),
            "kind": "unrecognized_binary",
            "severity": "review",  # reviewer judgment, not auto-fail
            "message": "unrecognized binary content",
        }]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 2

    findings: list[dict] = []
    if args.path.is_file():
        findings.extend(scan_one(args.path, args.path.parent))
    else:
        for p in sorted(args.path.rglob("*")):
            if not p.is_file():
                continue
            dir_parts = rel_dir_parts(p, args.path)
            if any(part in SKIP_DIRS for part in dir_parts):
                continue
            findings.extend(scan_one(p, args.path))

    hard = [f for f in findings if f["severity"] == "hard_fail"]
    soft = [f for f in findings if f["severity"] == "review"]
    info = [f for f in findings if f["severity"] == "info"]

    if args.json:
        print(json.dumps({"findings": findings}, indent=2))
    else:
        if hard:
            print(f"VENDOR/BINARY SCAN: {len(hard)} hard failure(s)\n")
            for f in hard:
                label = f.get("vendor", f["kind"])
                print(f"  [FAIL]  {f['file']}  ({label}: {f['message']})")
        if soft:
            print(f"\n{len(soft)} file(s) for reviewer attention:")
            for f in soft:
                print(f"  [CHECK] {f['file']}  ({f['message']})")
        if info:
            print(f"\n{len(info)} informational note(s) (do not gate CI):")
            for f in info:
                print(f"  [NOTE]  {f['file']}  ({f['message']})")
        if not (hard or soft):
            print("VENDOR/BINARY SCAN: clean.")
        elif hard:
            print("\nResult: FAIL — remove vendor/build binaries. Reference "
                  "vendor assemblies from the local install; see the ESAPI "
                  ".gitignore template.")
        else:
            print("\nResult: REVIEW — findings require reviewer sign-off.")

    return 1 if (hard or soft) else 0


if __name__ == "__main__":
    sys.exit(main())
