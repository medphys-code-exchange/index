#!/usr/bin/env python3
"""PHI scanner for code-index submissions.

Scans a directory tree (or a single file) for:
  1. DICOM files carrying populated patient-identifying tags.
  2. Text files containing PHI-like patterns (dates of birth, MRN-like
     identifiers, SSNs, patient-name-like DICOM dumps).
  3. Files that cannot be confidently scanned. These FAIL CLOSED and are
     reported as findings: unparseable DICOM-like files, unreadable files,
     text files too large to scan, office documents (.docx/.xlsx/... — PHI
     hides in embedded text and screenshots), and archives
     (.zip/.gz/.tgz/.tar/.7z/.rar — unpack or remove; the scanner never
     looks inside archives). Exception: .nii.gz is treated as image data,
     consistent with bare .nii.

Known limitations (reviewers are the backstop): PDF and image file contents
are not scanned — they instead raise a non-gating informational finding so a
reviewer is handed an explicit inspect-by-eye list; DICOM sequence items and
private tags are not walked.

Findings never echo tag or file contents — only the file path, tag
name/keyword or pattern label, and line number are reported, so CI logs
cannot leak PHI.

Exit codes: 0 = clean (or informational notes only), 1 = gating findings,
2 = usage/environment error.

Usage:
    python phi_scan.py <path> [--json]

<path> may be a directory (scanned recursively) or a single file.

Requires: pydicom (pip install pydicom). Text scanning works without it,
but DICOM files found without pydicom installed are reported as unscanned
findings (fail closed) — install it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pydicom
    from pydicom.datadict import dictionary_VR

    HAVE_PYDICOM = True
except ImportError:  # pragma: no cover
    HAVE_PYDICOM = False

# DICOM tags that must be empty/anonymized in any committed dataset.
# (group, element): human name
PHI_TAGS = {
    (0x0010, 0x0010): "PatientName",
    (0x0010, 0x0020): "PatientID",
    (0x0010, 0x0030): "PatientBirthDate",
    (0x0010, 0x1000): "OtherPatientIDs",
    (0x0010, 0x1001): "OtherPatientNames",
    (0x0010, 0x1040): "PatientAddress",
    (0x0010, 0x2154): "PatientTelephoneNumbers",
    (0x0010, 0x1090): "MedicalRecordLocator",
    (0x0008, 0x0090): "ReferringPhysicianName",
    (0x0008, 0x1048): "PhysiciansOfRecord",
    (0x0008, 0x1050): "PerformingPhysicianName",
    (0x0008, 0x0080): "InstitutionName",
    (0x0008, 0x0081): "InstitutionAddress",
    (0x0010, 0x21B0): "AdditionalPatientHistory",
    (0x0038, 0x0010): "AdmissionID",
}

# Values considered anonymized (case-insensitive). Placeholder identifiers
# shipped in template/seed DICOM files (e.g. DicomRTTool's template_RS.dcm,
# PatientName "Template") are explicitly allowed — they are not PHI.
ANON_OK = {
    "", "anonymous", "anon", "anonymized", "phantom", "test", "test^patient",
    "anonymous^patient", "qa", "physics", "synthetic", "template", "none",
    "na", "n/a", "unknown", "sample", "example", "demo",
}

# Text patterns. Conservative: tuned to catch obvious leaks, not to be a
# compliance product. Reviewers remain the backstop.
TEXT_PATTERNS = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("DOB-labeled", re.compile(
        r"(?i)\b(dob|date\s*of\s*birth|birth\s*date)\b\s*[:=]?\s*"
        r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}")),
    ("MRN-labeled", re.compile(
        r"(?i)\b(mrn|medical\s*record(\s*number)?)\b\s*[:=#]?\s*\d{5,}")),
    ("PatientName-dump", re.compile(
        r"(?i)patient'?s?\s*name\s*[:=]\s*[A-Z][a-z]+\s*\^?\s*[A-Z][a-z]+")),
    ("DICOM-name-tag-dump", re.compile(
        r"\(0010,\s*0010\)[^\n]*?[A-Z][A-Za-z]+\^[A-Z][A-Za-z]+")),
]

TEXT_EXTENSIONS = {
    ".py", ".cs", ".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".xml",
    ".ipynb", ".m", ".r", ".jl", ".toml", ".cfg", ".ini", ".log",
}

# Directory names skipped during a tree scan. Matching is case-insensitive
# and applies only to path components BELOW the scan root — an ancestor
# directory named e.g. 'venv' above the scan root does not exclude anything.
# NOTE: 'bin' and 'obj' are deliberately NOT skipped — PHI hides there too
# (the vendor-binary scanner handles build-output policy).
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

# Archives are never opened: fail closed.
ARCHIVE_EXTENSIONS = {".zip", ".gz", ".tgz", ".tar", ".7z", ".rar"}

# Office container formats: unscannable here, and PHI hides in embedded
# text and screenshots. Fail closed.
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}

# Documents/images whose contents this scanner cannot read (PDF text,
# burned-in identifiers on screenshots). These do NOT fail closed — a
# submission legitimately ships tutorial PDFs and figures — but they emit a
# non-gating informational finding so the reviewer is always handed an
# explicit "inspect these by eye" list instead of silent passes.
INFO_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff",
                   ".bmp"}

MAX_TEXT_BYTES = 5 * 1024 * 1024  # larger text files fail closed


def is_skipped(path: Path, root: Path) -> bool:
    """True if any directory component of path BELOW root is in SKIP_DIRS."""
    try:
        rel = path.relative_to(root)
    except ValueError:  # pragma: no cover - rglob always yields sub-paths
        rel = path
    return any(part.lower() in SKIP_DIRS for part in rel.parts[:-1])


def looks_dicom(path: Path) -> tuple[bool, bool]:
    """Cheap preamble check: 'DICM' magic at offset 128, or .dcm extension.

    Returns (is_dicom_like, read_error). A read error means the file could
    not be probed at all — callers must fail closed on it.
    """
    if path.suffix.lower() in {".dcm", ".dicom"}:
        return True, False
    try:
        with open(path, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM", False
    except OSError:
        return False, True


def _usable_dataset(ds) -> bool:
    """A force=True read of arbitrary bytes can yield a bogus dataset of
    unrecognized tags. Consider the dataset usable only if it has file meta
    information or at least one tag known to the DICOM dictionary."""
    if len(ds) == 0:
        return False
    file_meta = getattr(ds, "file_meta", None)
    if file_meta is not None and len(file_meta) > 0:
        return True
    for elem in ds:
        try:
            dictionary_VR(elem.tag)
            return True
        except KeyError:
            continue
    return False


def scan_dicom(path: Path) -> list[dict]:
    ds = None
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=False)
    except Exception:
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True,
                                 force=True)
        except Exception:
            ds = None
    if ds is None or not _usable_dataset(ds):
        # Fail closed: a DICOM-like file we cannot parse is unscanned.
        return [{
            "file": str(path),
            "kind": "unparseable_dicom",
            "message": ("DICOM-like file could not be parsed - "
                        "unscanned, treat as containing PHI (fail closed)"),
        }]
    findings = []
    for (group, elem), name in PHI_TAGS.items():
        tag_val = ds.get((group, elem))
        if tag_val is None:
            continue
        value = str(tag_val.value).strip() if tag_val.value is not None else ""
        if value.lower().replace(" ", "") in ANON_OK:
            continue
        if value:
            # Never echo the value itself — tag identity and file only.
            findings.append({
                "file": str(path),
                "kind": "dicom_tag",
                "tag": f"({group:04X},{elem:04X}) {name}",
            })
    return findings


def scan_text(path: Path) -> list[dict]:
    findings = []
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            # Fail closed: a file too large to scan cannot be cleared.
            return [{
                "file": str(path),
                "kind": "too_large_unscanned",
                "message": (f"text file exceeds {MAX_TEXT_BYTES} bytes - "
                            "unscanned (fail closed); split or remove"),
            }]
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        # Fail closed: unreadable file cannot be cleared.
        return [{
            "file": str(path),
            "kind": "unreadable",
            "message": "file could not be read - unscanned (fail closed)",
        }]
    for label, pattern in TEXT_PATTERNS:
        for m in pattern.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            findings.append({
                "file": str(path),
                "kind": "text_pattern",
                "pattern": label,
                "line": line_no,
            })
    return findings


def scan_file(path: Path, counters: dict) -> list[dict]:
    ext = path.suffix.lower()
    # .nii.gz is compressed single-image data, not a container archive —
    # treated like bare .nii (which is not scanned either).
    if path.name.lower().endswith(".nii.gz"):
        return []
    if ext in ARCHIVE_EXTENSIONS:
        return [{
            "file": str(path),
            "kind": "archive_unscanned",
            "message": "archive cannot be scanned for PHI - unpack or remove",
        }]
    if ext in OFFICE_EXTENSIONS:
        return [{
            "file": str(path),
            "kind": "office_unscanned",
            "message": ("office document cannot be scanned for PHI - "
                        "remove it or have the reviewer inspect it"),
        }]
    if ext in INFO_EXTENSIONS:
        return [{
            "file": str(path),
            "kind": "unscannable_document",
            "severity": "info",
            "message": ("document/image contents not scanned - reviewer must "
                        "confirm no PHI (e.g. burned-in identifiers)"),
        }]
    dicom_like, read_error = looks_dicom(path)
    if read_error:
        return [{
            "file": str(path),
            "kind": "unreadable",
            "message": "file could not be read - unscanned (fail closed)",
        }]
    if dicom_like:
        counters["dicom_files"] += 1
        if HAVE_PYDICOM:
            return scan_dicom(path)
        return []
    if ext in TEXT_EXTENSIONS:
        return scan_text(path)
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 2

    counters = {"dicom_files": 0}
    findings: list[dict] = []
    if args.path.is_file():
        findings.extend(scan_file(args.path, counters))
    else:
        for p in sorted(args.path.rglob("*")):
            if not p.is_file():
                continue
            if is_skipped(p, args.path):
                continue
            findings.extend(scan_file(p, counters))

    if counters["dicom_files"] and not HAVE_PYDICOM:
        print(
            f"warning: {counters['dicom_files']} DICOM file(s) found but "
            "pydicom is not installed — DICOM tags NOT scanned. Install "
            "pydicom.",
            file=sys.stderr,
        )
        # Fail closed: unscanned DICOM in a submission is a finding.
        findings.append({
            "file": "(scanner)",
            "kind": "unscanned_dicom",
            "count": counters["dicom_files"],
        })

    # Informational findings (unscannable PDFs/images) never gate CI; only
    # real or fail-closed findings set the exit code.
    gating = [f for f in findings if f.get("severity") != "info"]
    info = [f for f in findings if f.get("severity") == "info"]

    if args.json:
        print(json.dumps({"findings": findings}, indent=2))
    else:
        if gating:
            print(f"PHI SCAN: {len(gating)} finding(s)\n")
            for f in gating:
                if f["kind"] == "dicom_tag":
                    print(f"  [DICOM] {f['file']}\n"
                          f"          {f['tag']} is populated")
                elif f["kind"] == "text_pattern":
                    print(f"  [TEXT]  {f['file']}:{f['line']}  ({f['pattern']})")
                elif f["kind"] == "unscanned_dicom":
                    print(f"  [WARN]  {f['count']} DICOM file(s) not scanned "
                          "(pydicom missing)")
                else:
                    print(f"  [WARN]  {f['file']}  ({f['message']})")
        if info:
            print(f"\n{len(info)} document(s)/image(s) for reviewer eyes "
                  "(do not gate CI):")
            for f in info:
                print(f"  [NOTE]  {f['file']}  ({f['message']})")
        if not gating:
            print("PHI SCAN: clean.")
        else:
            print("\nResult: FAIL — remove or anonymize before submission.")

    return 1 if gating else 0


if __name__ == "__main__":
    sys.exit(main())
