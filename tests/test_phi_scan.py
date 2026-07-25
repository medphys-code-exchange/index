"""Tests for scripts/phi_scan.py — fail-closed behavior of the PHI gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "phi_scan.py"

SSN_LINE = "patient ssn: 123-45-6789\n"


def run_scan(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True,
    )


def run_json(path: Path):
    proc = run_scan(path, "--json")
    findings = json.loads(proc.stdout)["findings"]
    return proc, findings


def write_dicom(path: Path, patient_name: str, patient_id: str = "") -> None:
    """Write a valid minimal DICOM file with pydicom."""
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.Modality = "CT"
    ds.save_as(str(path), enforce_file_format=True)


# ---------------------------------------------------------------- DICOM


def test_valid_dicom_with_phi_fails(tmp_path):
    write_dicom(tmp_path / "ct.dcm", "Doe^John", "MRN0012345")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    tags = [f["tag"] for f in findings if f["kind"] == "dicom_tag"]
    assert any("PatientName" in t for t in tags)
    assert any("PatientID" in t for t in tags)


def test_phi_values_never_echoed(tmp_path):
    """Finding output must not leak the tag value into CI logs."""
    write_dicom(tmp_path / "ct.dcm", "Doe^John", "MRN0012345")
    for extra in (["--json"], []):
        proc = run_scan(tmp_path, *extra)
        assert proc.returncode == 1
        assert "Doe" not in proc.stdout
        assert "MRN0012345" not in proc.stdout


def test_anonymized_dicom_clean(tmp_path):
    write_dicom(tmp_path / "ct.dcm", "Anonymous")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


def test_unparseable_dcm_fails_closed(tmp_path):
    """A .dcm that pydicom cannot parse (even force=True) is a finding,
    not a silent pass — the raw bytes here contain PHI-like content."""
    (tmp_path / "broken.dcm").write_bytes(
        b"Patient Name: Doe^John\nSSN: 123-45-6789\nMRN: 8675309\n")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert [f["kind"] for f in findings] == ["unparseable_dicom"]
    assert "unscanned" in findings[0]["message"]


def test_unparseable_dcm_binary_garbage_fails_closed(tmp_path):
    (tmp_path / "junk.dcm").write_bytes(os.urandom(64))
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "unparseable_dicom"


# ---------------------------------------------------------------- single file


def test_single_file_text_is_scanned(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text(SSN_LINE)
    proc, findings = run_json(f)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "text_pattern"
    assert findings[0]["pattern"] == "SSN"


def test_single_file_dicom_is_scanned(tmp_path):
    f = tmp_path / "ct.dcm"
    write_dicom(f, "Doe^John")
    proc, findings = run_json(f)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "dicom_tag"


def test_single_clean_file_exit0(tmp_path):
    f = tmp_path / "readme.md"
    f.write_text("A clean readme with no identifiers.\n")
    proc, findings = run_json(f)
    assert proc.returncode == 0
    assert findings == []


def test_nonexistent_path_exit2(tmp_path):
    proc = run_scan(tmp_path / "does_not_exist")
    assert proc.returncode == 2
    assert "not found" in proc.stderr


# ---------------------------------------------------------------- text


def test_ssn_pattern_in_tree(tmp_path):
    (tmp_path / "config.py").write_text("# " + SSN_LINE)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "text_pattern"


def test_clean_tree_exit0(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "README.md").write_text("Nothing personal here.\n")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


# ---------------------------------------------------------------- archives


@pytest.mark.parametrize("name", ["data.zip", "data.tar", "data.tgz",
                                  "logs.gz", "old.7z", "old.rar"])
def test_archive_is_a_finding(tmp_path, name):
    p = tmp_path / name
    if name.endswith(".zip"):
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("inner.txt", SSN_LINE)
    else:
        p.write_bytes(b"\x1f\x8b\x00\x00opaque")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "archive_unscanned"
    assert "unpack or remove" in findings[0]["message"]


def test_nii_gz_is_not_an_archive_finding(tmp_path):
    """.nii.gz is compressed image data, treated like bare .nii (unscanned,
    clean) rather than an opaque archive."""
    (tmp_path / "vol.nii.gz").write_bytes(b"\x1f\x8b\x00\x00opaque")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


def test_office_document_is_a_finding(tmp_path):
    (tmp_path / "notes.docx").write_bytes(b"PK\x03\x04opaque")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "office_unscanned"


def test_template_placeholder_dicom_is_clean(tmp_path):
    """Shipped template/seed DICOMs (e.g. DicomRTTool's template_RS.dcm with
    PatientName 'Template') are placeholders, not PHI — must not gate."""
    write_dicom(tmp_path / "template_RS.dcm", "Template", "TEMPLATE")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


def test_pdf_is_informational_not_gating(tmp_path):
    """A tutorial PDF cannot be scanned, but it must not fail closed — it
    raises a non-gating informational note so the reviewer inspects it."""
    (tmp_path / "tutorial.pdf").write_bytes(b"%PDF-1.7\nopaque\n")
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert len(findings) == 1
    assert findings[0]["kind"] == "unscannable_document"
    assert findings[0]["severity"] == "info"


def test_info_findings_do_not_mask_real_phi(tmp_path):
    """An info-tier PDF alongside a real PHI leak still exits 1."""
    (tmp_path / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "leak.txt").write_text(SSN_LINE)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    kinds = {f["kind"] for f in findings}
    assert "text_pattern" in kinds
    assert "unscannable_document" in kinds


def test_oversize_text_file_fails_closed(tmp_path):
    big = tmp_path / "huge.log"
    big.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "too_large_unscanned"


# ---------------------------------------------------------------- skip dirs


def test_bin_and_obj_dirs_are_scanned(tmp_path):
    """PHI hiding in bin/ or obj/ must be found — those dirs are no longer
    skipped by the PHI scanner."""
    for d in ("bin", "obj"):
        sub = tmp_path / d
        sub.mkdir()
        (sub / "dump.txt").write_text(SSN_LINE)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 1
    assert len(findings) == 2


def test_skip_dirs_case_insensitive(tmp_path):
    sub = tmp_path / "VENV"
    sub.mkdir()
    (sub / "leak.txt").write_text(SSN_LINE)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


def test_ancestor_skip_dir_does_not_exclude(tmp_path):
    """A directory named 'venv' ABOVE the scan root must not exclude the
    whole tree — only components below the root count."""
    root = tmp_path / "venv" / "project"
    root.mkdir(parents=True)
    (root / "leak.txt").write_text(SSN_LINE)
    proc, findings = run_json(root)
    assert proc.returncode == 1
    assert findings[0]["kind"] == "text_pattern"


def test_skip_dir_below_root_still_skipped(tmp_path):
    sub = tmp_path / "node_modules" / "pkg"
    sub.mkdir(parents=True)
    (sub / "leak.txt").write_text(SSN_LINE)
    proc, findings = run_json(tmp_path)
    assert proc.returncode == 0
    assert findings == []


# ---------------------------------------------------------------- unreadable


@pytest.mark.skipif(os.name == "nt",
                    reason="chmod 000 does not block reads on Windows")
@pytest.mark.skipif(os.name != "nt" and os.geteuid() == 0,
                    reason="root ignores file permissions")
def test_unreadable_file_fails_closed(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text(SSN_LINE)
    f.chmod(0)
    try:
        proc, findings = run_json(tmp_path)
        assert proc.returncode == 1
        assert findings[0]["kind"] == "unreadable"
    finally:
        f.chmod(0o644)


# ---------------------------------------------------------------- standalone


def test_standalone_on_repo_scripts_dir():
    """The scanner must run without crashing on the repo's own scripts/."""
    proc = run_scan(REPO / "scripts", "--json")
    assert proc.returncode in (0, 1)
    json.loads(proc.stdout)  # output stays machine-readable
