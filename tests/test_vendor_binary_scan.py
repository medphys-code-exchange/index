"""Tests for scripts/vendor_binary_scan.py — extension-agnostic vendor
detection, archive hard-fails, and scan-root-relative build-dir matching."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "vendor_binary_scan.py"

BINARY_BYTES = b"MZ\x90\x00\x03\x00\x00\x00PE\x00\x00"  # PE-ish, has NULs


def run_scan(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True,
    )


def run_json(path: Path):
    proc = run_scan(path, "--json")
    findings = json.loads(proc.stdout)["findings"]
    return proc, findings


# ------------------------------------------------- vendor names, any extension


def test_renamed_vendor_dll_bak_hard_fails(tmp_path):
    """'VMS.TPS.Common.Model.API.dll.bak' must not escape the hard fail."""
    (tmp_path / "VMS.TPS.Common.Model.API.dll.bak").write_bytes(BINARY_BYTES)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "vendor_binary"
    assert findings[0]["severity"] == "hard_fail"
    assert findings[0]["vendor"] == "Varian ESAPI"


def test_renamed_vendor_dll_bak_hard_fails_even_with_text_content(tmp_path):
    """.dll anywhere in the name is binary-suggesting: hard fail regardless
    of content."""
    (tmp_path / "VMS.TPS.Common.Model.API.dll.old").write_text("stub")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["severity"] == "hard_fail"


def test_extensionless_vendor_binary_hard_fails(tmp_path):
    (tmp_path / "VMS.TPS.Common.Model.API").write_bytes(BINARY_BYTES)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "vendor_binary"
    assert findings[0]["severity"] == "hard_fail"


def test_vendor_name_on_text_file_is_info_and_exit0(tmp_path):
    """A clearly-text file merely named after a vendor (raystation_export.py,
    varian_esapi_notes.md — legitimate in-scope naming per decision 5) is an
    informational note only and must NOT gate CI."""
    (tmp_path / "varian_esapi_notes.md").write_text(
        "Notes about talking to the TPS.\n")
    (tmp_path / "raystation_export.py").write_text("print('hi')\n")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert len(findings) == 2
    assert all(f["kind"] == "vendor_name" for f in findings)
    assert all(f["severity"] == "info" for f in findings)


def test_nii_gz_is_allowlisted_data_not_archive(tmp_path):
    """.nii.gz (compressed NIfTI) is standard medical-image data, not a
    container archive — must pass clean like bare .nii."""
    (tmp_path / "brain.nii.gz").write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 32)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


def test_single_file_vendor_dll(tmp_path):
    f = tmp_path / "VMS.TPS.Common.Model.API.dll"
    f.write_bytes(BINARY_BYTES)
    proc, findings = run_json(f)
    assert proc.returncode == 1
    assert findings[0]["severity"] == "hard_fail"


# ------------------------------------------------------------------- archives


def test_zip_with_vendor_dll_name_hard_fails_and_names_entry(tmp_path):
    p = tmp_path / "release.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("lib/VMS.TPS.Common.Model.API.dll", BINARY_BYTES)
        zf.writestr("readme.txt", "hello")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "archive"
    assert findings[0]["severity"] == "hard_fail"
    assert "VMS.TPS.Common.Model.API.dll" in findings[0]["message"]


def test_plain_archive_hard_fails(tmp_path):
    p = tmp_path / "data.tar.gz"
    with tarfile.open(p, "w:gz") as tf:
        inner = tmp_path / "inner.txt"
        inner.write_text("hello")
        tf.add(inner, arcname="inner.txt")
    inner.unlink()
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "archive"
    assert "unpack or remove" in findings[0]["message"]


@pytest.mark.parametrize("name", ["x.zip", "x.gz", "x.7z", "x.rar", "x.tar"])
def test_archives_not_allowlisted(tmp_path, name):
    (tmp_path / name).write_bytes(b"\x00opaque")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "archive"
    assert findings[0]["severity"] == "hard_fail"


# ------------------------------------------------------------------ build dirs


def test_bin_dir_text_only_is_review_exit1(tmp_path):
    sub = tmp_path / "bin"
    sub.mkdir()
    (sub / "run.sh").write_text("#!/bin/sh\necho hi\n")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "build_dir_text"
    assert findings[0]["severity"] == "review"


def test_bin_dir_binary_hard_fails(tmp_path):
    sub = tmp_path / "obj"
    sub.mkdir()
    (sub / "app.cache").write_bytes(BINARY_BYTES)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "build_output_committed"
    assert findings[0]["severity"] == "hard_fail"


def test_build_dir_matching_case_insensitive(tmp_path):
    sub = tmp_path / "Bin"
    sub.mkdir()
    (sub / "thing.exe").write_bytes(BINARY_BYTES)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["severity"] == "hard_fail"


def test_ancestor_bin_dir_does_not_fail_everything(tmp_path):
    """A directory named 'bin' ABOVE the scan root must not condemn the
    tree — only components below the root count."""
    root = tmp_path / "bin" / "project"
    root.mkdir(parents=True)
    (root / "main.py").write_text("print('ok')\n")
    proc, findings = run_json(root)
    assert proc.returncode == 0
    assert findings == []


# ----------------------------------------------------------------- exit codes


def test_clean_tree_exit0(tmp_path):
    (tmp_path / "main.py").write_text("print('ok')\n")
    (tmp_path / "README.md").write_text("docs\n")
    (tmp_path / "scan.mha").write_bytes(b"\x00binary imaging data")  # allowlisted
    (tmp_path / "ct.dcm").write_bytes(b"\x00" * 16)  # allowlisted
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


def test_disallowed_binary_extension_hard_fails(tmp_path):
    (tmp_path / "helper.dll").write_bytes(BINARY_BYTES)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "binary_artifact"


def test_unrecognized_binary_is_review_exit1(tmp_path):
    (tmp_path / "mystery.dat").write_bytes(BINARY_BYTES)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "unrecognized_binary"
    assert findings[0]["severity"] == "review"


def test_nonexistent_path_exit2(tmp_path):
    proc = run_scan(tmp_path / "missing")
    assert proc.returncode == 2
    assert "not found" in proc.stderr


def test_single_file_clean_exit0(tmp_path):
    f = tmp_path / "script.py"
    f.write_text("print('ok')\n")
    proc, findings = run_json(f)
    assert proc.returncode == 0
    assert findings == []


# ---------------------------------------------------------------- standalone


def test_standalone_on_repo_scripts_dir():
    proc = run_scan(REPO / "scripts", "--json")
    assert proc.returncode in (0, 1)
    json.loads(proc.stdout)
