"""Tests for scripts/generate_phantom.py — the synthetic phantom dataset.

Verifies the generated dataset against docs/phantom_dataset_spec.md:
readability, UID cross-references, contour-derived volumes/centroids vs the
spec's known-correct table, dose statistics, byte-level determinism, and a
clean pass of the repo's own PHI and vendor-binary scanners.

Volumes and dose statistics are recomputed here from the emitted contour
and dose data (shoelace areas, point-in-polygon voxel selection) — never
echoed from the generator's analytic formulas.
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pydicom
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "generate_phantom.py"
PHI_SCAN = REPO / "scripts" / "phi_scan.py"
VENDOR_SCAN = REPO / "scripts" / "vendor_binary_scan.py"

# Spec known-correct table (docs/phantom_dataset_spec.md): value, tolerance %.
# Cavity_Air is not in the spec table; it is a sphere the same size as GTV,
# so the GTV row's value/tolerance apply.
SPEC_VOLUMES_CM3 = {
    "External": (6283.2, 1.0),
    "PTV": (65.45, 2.0),
    "GTV": (4.19, 3.0),
    "SpinalCord": (15.71, 2.0),
    "Parotid_L": (14.14, 2.0),
    "Cavity_Air": (4.19, 3.0),
}
SPEC_CENTROIDS_MM = {
    "External": (0.0, 0.0, 0.0),
    "PTV": (0.0, 0.0, 0.0),
    "GTV": (0.0, 0.0, 0.0),
    "SpinalCord": (0.0, 60.0, 0.0),
    "Parotid_L": (50.0, -20.0, 20.0),
    "Cavity_Air": (-50.0, -20.0, -20.0),
}
SPEC_ROI_NUMBERS = {
    "External": 1, "PTV": 2, "GTV": 3,
    "SpinalCord": 4, "Parotid_L": 5, "Cavity_Air": 6,
}
PRESCRIPTION_GY = 60.0
# Closed-form SpinalCord D_max: d = (60 - 5) - 25 = 30 mm from the PTV
# surface -> 60 * (1 - 30/50) = 24 Gy.
SPEC_CORD_DMAX_GY = 24.0
# Closed-form External integral dose = 12500 * pi Gy cm^3 (spec falloff).
SPEC_INTEGRAL_GY_CM3 = 12500.0 * math.pi
FALLOFF_END_MM = 25.0 + 50.0  # PTV radius + falloff length


# ---------------------------------------------------------------- fixtures


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_phantom", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def phantom_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("phantom") / "dataset"
    _load_generator().generate(out)
    return out


@pytest.fixture(scope="session")
def loaded(phantom_dir):
    cts = [pydicom.dcmread(str(p))
           for p in sorted(phantom_dir.glob("CT_*.dcm"))]
    return {
        "cts": cts,
        "rtstruct": pydicom.dcmread(str(phantom_dir / "RTSTRUCT.dcm")),
        "rtplan": pydicom.dcmread(str(phantom_dir / "RTPLAN.dcm")),
        "rtdose": pydicom.dcmread(str(phantom_dir / "RTDOSE.dcm")),
    }


# ------------------------------------------------- independent geometry math


def shoelace_area(xy: np.ndarray) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1))
                           - np.dot(np.roll(x, -1), y)))


def polygon_mask(xg: np.ndarray, yg: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Even-odd (crossing number) point-in-polygon for grid points."""
    inside = np.zeros(xg.shape, dtype=bool)
    n = len(xy)
    for i in range(n):
        x0, y0 = xy[i]
        x1, y1 = xy[(i + 1) % n]
        crosses = (y0 > yg) != (y1 > yg)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = x0 + (yg - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (xg < x_at)
    return inside


def contours_by_name(rtstruct) -> dict[str, list[tuple[float, np.ndarray]]]:
    """{ROIName: [(z, (N, 2) in-plane vertices), ...]} from ContourData."""
    names = {roi.ROINumber: str(roi.ROIName)
             for roi in rtstruct.StructureSetROISequence}
    out: dict[str, list[tuple[float, np.ndarray]]] = {}
    for rc in rtstruct.ROIContourSequence:
        contours = []
        for c in rc.ContourSequence:
            assert c.ContourGeometricType == "CLOSED_PLANAR"
            pts = np.asarray([float(v) for v in c.ContourData]).reshape(-1, 3)
            zs = pts[:, 2]
            assert np.ptp(zs) < 1e-6  # planar
            contours.append((float(zs[0]), pts[:, :2]))
        out[names[rc.ReferencedROINumber]] = contours
    return out


def slab_thickness_mm(contours: list[tuple[float, np.ndarray]]) -> float:
    """Slice spacing inferred from the contour planes themselves."""
    zs = sorted(z for z, _ in contours)
    diffs = np.diff(zs)
    assert len(diffs) > 0
    assert np.allclose(diffs, diffs[0])
    return float(diffs[0])


def volume_cm3(contours: list[tuple[float, np.ndarray]]) -> float:
    dz = slab_thickness_mm(contours)
    return sum(shoelace_area(xy) * dz for _, xy in contours) / 1000.0


def centroid_mm(contours: list[tuple[float, np.ndarray]]) -> np.ndarray:
    total_area = 0.0
    weighted = np.zeros(3)
    for z, xy in contours:
        area = shoelace_area(xy)
        cx, cy = xy.mean(axis=0)
        weighted += area * np.array([cx, cy, z])
        total_area += area
    return weighted / total_area


def dose_grid(rtdose):
    """(dose Gy array [frame, row, col], x centers, y centers, frame z's)."""
    dose = rtdose.pixel_array.astype(np.float64) * float(rtdose.DoseGridScaling)
    ipp = [float(v) for v in rtdose.ImagePositionPatient]
    spacing = [float(v) for v in rtdose.PixelSpacing]  # [row, col]
    xs = ipp[0] + np.arange(rtdose.Columns) * spacing[1]
    ys = ipp[1] + np.arange(rtdose.Rows) * spacing[0]
    zs = np.asarray([ipp[2] + float(v)
                     for v in rtdose.GridFrameOffsetVector])
    return dose, xs, ys, zs


def doses_in_structure(rtdose, contours) -> np.ndarray:
    """Dose samples at grid points whose centers fall inside the contours."""
    dose, xs, ys, zs = dose_grid(rtdose)
    xg, yg = np.meshgrid(xs, ys)
    values = []
    for z, xy in contours:
        frame = np.flatnonzero(np.abs(zs - z) < 1e-3)
        if frame.size == 0:
            continue
        mask = polygon_mask(xg, yg, xy)
        values.append(dose[frame[0]][mask])
    assert values, "no dose frames matched the contour planes"
    return np.concatenate(values)


# ---------------------------------------------------------------- modalities


def test_all_modalities_written_and_readable(phantom_dir, loaded):
    assert len(loaded["cts"]) == 108
    assert all(ct.Modality == "CT" for ct in loaded["cts"])
    assert loaded["rtstruct"].Modality == "RTSTRUCT"
    assert loaded["rtplan"].Modality == "RTPLAN"
    assert loaded["rtdose"].Modality == "RTDOSE"
    # Pixel data decodes.
    assert loaded["cts"][0].pixel_array.shape == (256, 256)
    assert loaded["rtdose"].pixel_array.shape[1:] == (128, 128)
    # Companion artifacts exist.
    assert (phantom_dir / "reference_values.json").is_file()
    assert (phantom_dir / "manifest.json").is_file()


def test_patient_module_consistent_and_synthetic(loaded):
    objects = ([loaded["rtstruct"], loaded["rtplan"], loaded["rtdose"]]
               + loaded["cts"])
    for ds in objects:
        assert str(ds.PatientName) == "Phantom"
        assert ds.PatientID == "PHANTOM"
        assert ds.PatientBirthDate == ""


# ---------------------------------------------------------------- UID chain


def test_uid_cross_reference_chain(loaded):
    cts = loaded["cts"]
    rtstruct, rtplan, rtdose = (loaded["rtstruct"], loaded["rtplan"],
                                loaded["rtdose"])
    frame_uid = cts[0].FrameOfReferenceUID
    ct_series_uid = cts[0].SeriesInstanceUID
    ct_sops = {ct.SOPInstanceUID for ct in cts}

    # One CT series, one study, one frame of reference.
    assert all(ct.SeriesInstanceUID == ct_series_uid for ct in cts)
    assert all(ct.FrameOfReferenceUID == frame_uid for ct in cts)
    study_uid = cts[0].StudyInstanceUID
    for ds in [rtstruct, rtplan, rtdose] + cts:
        assert ds.StudyInstanceUID == study_uid

    # RTSTRUCT -> frame of reference -> CT series -> every CT instance.
    for_item = rtstruct.ReferencedFrameOfReferenceSequence[0]
    assert for_item.FrameOfReferenceUID == frame_uid
    series_item = for_item.RTReferencedStudySequence[0] \
        .RTReferencedSeriesSequence[0]
    assert series_item.SeriesInstanceUID == ct_series_uid
    referenced = {item.ReferencedSOPInstanceUID
                  for item in series_item.ContourImageSequence}
    assert referenced == ct_sops
    for roi in rtstruct.StructureSetROISequence:
        assert roi.ReferencedFrameOfReferenceUID == frame_uid
    # Every contour references a real CT slice.
    for rc in rtstruct.ROIContourSequence:
        for c in rc.ContourSequence:
            ref = c.ContourImageSequence[0].ReferencedSOPInstanceUID
            assert ref in ct_sops

    # RTPLAN -> RTSTRUCT; RTDOSE -> RTPLAN; shared frame of reference.
    assert rtplan.FrameOfReferenceUID == frame_uid
    assert rtdose.FrameOfReferenceUID == frame_uid
    plan_ss = rtplan.ReferencedStructureSetSequence[0]
    assert plan_ss.ReferencedSOPInstanceUID == rtstruct.SOPInstanceUID
    dose_plan = rtdose.ReferencedRTPlanSequence[0]
    assert dose_plan.ReferencedSOPInstanceUID == rtplan.SOPInstanceUID


def test_uids_deterministic_shape(loaded):
    """UIDs live under the UUID-derived 2.25. root and respect the 64-char
    DICOM limit (spec DICOM conformance)."""
    for ds in loaded["cts"] + [loaded["rtstruct"], loaded["rtplan"],
                               loaded["rtdose"]]:
        for uid in (ds.SOPInstanceUID, ds.SeriesInstanceUID,
                    ds.StudyInstanceUID):
            assert uid.startswith("2.25.")
            assert len(uid) <= 64


# ---------------------------------------------------------------- structures


def test_tg263_names_and_fixed_roi_numbers(loaded):
    rois = {str(roi.ROIName): roi.ROINumber
            for roi in loaded["rtstruct"].StructureSetROISequence}
    assert rois == SPEC_ROI_NUMBERS


def test_volumes_match_spec_within_tolerance(loaded):
    contours = contours_by_name(loaded["rtstruct"])
    for name, (expected, tol_pct) in SPEC_VOLUMES_CM3.items():
        actual = volume_cm3(contours[name])
        diff_pct = abs(actual - expected) / expected * 100.0
        assert diff_pct <= tol_pct, \
            f"{name}: {actual:.3f} cm^3 vs {expected} cm^3 " \
            f"({diff_pct:.2f}% > {tol_pct}%)"


def test_centroids_match_spec_within_1mm(loaded):
    contours = contours_by_name(loaded["rtstruct"])
    for name, expected in SPEC_CENTROIDS_MM.items():
        actual = centroid_mm(contours[name])
        offset = np.linalg.norm(actual - np.asarray(expected))
        assert offset <= 1.0, f"{name}: centroid {actual} vs {expected}"


# ---------------------------------------------------------------- dose model


def test_ptv_dose_uniform_60gy(loaded):
    contours = contours_by_name(loaded["rtstruct"])
    ptv = doses_in_structure(loaded["rtdose"], contours["PTV"])
    assert ptv.size > 5000  # a real sample, not a handful of voxels
    for stat in (ptv.mean(), ptv.min(), ptv.max()):
        assert abs(stat - PRESCRIPTION_GY) / PRESCRIPTION_GY <= 0.005


def test_spinalcord_dmax_near_closed_form(loaded):
    """Voxelized cord D_max vs the 24 Gy closed form. The maximum lives at
    a single tangent point (0, 55, 0); a 2 mm dose grid systematically
    undersamples it, so the band is asymmetric (never above analytic,
    reasonably close below). See reference_values.json note."""
    contours = contours_by_name(loaded["rtstruct"])
    cord = doses_in_structure(loaded["rtdose"], contours["SpinalCord"])
    dmax = cord.max()
    assert dmax <= SPEC_CORD_DMAX_GY * 1.005
    assert dmax >= SPEC_CORD_DMAX_GY * 0.94


def test_dose_zero_outside_falloff(loaded):
    dose, xs, ys, zs = dose_grid(loaded["rtdose"])
    xg, yg = np.meshgrid(xs, ys)
    for i, z in enumerate(zs):
        radius = np.sqrt(xg ** 2 + yg ** 2 + z ** 2)
        beyond = dose[i][radius > FALLOFF_END_MM + 1.0]
        assert beyond.size == 0 or beyond.max() == 0.0


def test_integral_dose_matches_closed_form(loaded):
    dose, xs, ys, zs = dose_grid(loaded["rtdose"])
    voxel_cm3 = ((xs[1] - xs[0]) * (ys[1] - ys[0]) * (zs[1] - zs[0])) / 1000.0
    integral = dose.sum() * voxel_cm3
    diff_pct = abs(integral - SPEC_INTEGRAL_GY_CM3) / SPEC_INTEGRAL_GY_CM3 * 100
    assert diff_pct <= 2.0


def test_reference_values_json_carries_analytic_table(phantom_dir):
    ref = json.loads((phantom_dir / "reference_values.json").read_text())
    assert ref["dataset_version"] == "phantom-v1.0.0"
    assert ref["structures"]["PTV"]["volume_cm3"] == \
        pytest.approx(65.45, rel=1e-3)
    assert ref["dose"]["SpinalCord"]["d_max_gy"] == pytest.approx(24.0)
    assert ref["dose"]["External"]["integral_dose_gy_cm3"] == \
        pytest.approx(SPEC_INTEGRAL_GY_CM3, rel=1e-6)


# ------------------------------------------------------------- determinism


def test_regeneration_is_byte_identical(phantom_dir, tmp_path):
    """Second run (via the CLI, in a fresh directory) must produce the same
    SHA-256 for every file — the spec's byte-identical regeneration rule."""
    out2 = tmp_path / "phantom2"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(out2)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    manifest1 = json.loads((phantom_dir / "manifest.json").read_text())
    manifest2 = json.loads((out2 / "manifest.json").read_text())
    assert manifest1["files"] == manifest2["files"]
    assert len(manifest1["files"]) == 108 + 4  # CT + RT objects + reference


# ------------------------------------------------------------- repo scanners


def test_phi_scan_clean_on_dataset(phantom_dir):
    proc = subprocess.run(
        [sys.executable, str(PHI_SCAN), str(phantom_dir)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_vendor_binary_scan_clean_on_dataset(phantom_dir):
    proc = subprocess.run(
        [sys.executable, str(VENDOR_SCAN), str(phantom_dir)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
