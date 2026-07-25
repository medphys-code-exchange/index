#!/usr/bin/env python3
"""Synthetic phantom DICOM-RT dataset generator.

Implements docs/phantom_dataset_spec.md (v0.1): a CT series, an RTSTRUCT,
a minimal RTPLAN, and an RTDOSE with analytically known geometry and dose,
usable as the standard test target for code-index submissions.

Design properties (spec "Generation" section):
  * Deterministic — fixed dates, no timestamps, no randomness. UIDs are
    derived by hashing (dataset version | object kind) under a UUID-derived
    "2.25." root, so running the generator twice at the same version
    produces byte-identical files.
  * The generator is the source of truth; the DICOM is a build artifact.
  * Emits, next to the DICOM: reference_values.json (analytic known-correct
    outputs, computed from the geometry/dose FORMULAS, never from the
    voxelized data) and manifest.json (SHA-256 of every emitted file).
  * Zero PHI by construction; the output must pass scripts/phi_scan.py and
    scripts/vendor_binary_scan.py clean. Patient identifiers are drawn from
    phi_scan.py's ANON_OK allowlist ("Phantom"/"PHANTOM"; empty birth date).

Exit codes: 0 = success, 2 = usage error.

Usage:
    python generate_phantom.py [output_dir]        (default: ./data/phantom)

Requires: pydicom, numpy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import uuid
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian
import pydicom

# =========================================================================
# PARAMETERS — proposed defaults for every [OPEN] item in
# docs/phantom_dataset_spec.md v0.1. All of these are provisional until
# Brian signs off (spec, Acceptance criterion 6). Adjust here only.
# =========================================================================

DATASET_VERSION = "phantom-v1.0.0"

# --- CT grid [OPEN — proposed: 256x256, 1.0 mm pixels, 2.0 mm slices,
#     ~110 slices covering z in [-108, +108]].
# 108 slices with centers at odd integers -107..+107 mm cover exactly
# [-108, +108] mm edge-to-edge. Odd-integer slice centers also mean the
# cylinder end caps at z = +/-100 fall on slice BOUNDARIES, so
# contour-derived cylinder volumes are exact rather than off by half a
# slice at each end.
CT_ROWS = 256
CT_COLS = 256
CT_PIXEL_SPACING_MM = 1.0            # in-plane, both axes
CT_SLICE_THICKNESS_MM = 2.0
CT_NUM_SLICES = 108
CT_Z_FIRST_MM = -107.0               # center of first (lowest) slice
CT_IPP_XY_MM = (-127.5, -127.5)      # center of first pixel (col 0, row 0)
HU_AIR = -1000                       # outside External
CT_RESCALE_INTERCEPT = -1024

# --- Geometry [OPEN — proposed]. mm, DICOM patient coordinates, HFS.
# Painted onto the CT in list order (GTV after PTV so the concentric
# override lands correctly). ROI numbers are fixed and documented
# (spec: lookup-by-name AND lookup-by-number must be testable).
STRUCTURES = [
    # name, roi_number, shape, params, HU, RTROIInterpretedType, color,
    # volume tolerance (% — spec known-correct table; Cavity_Air is not in
    # the spec table, GTV's +/-3 % is used for the identically sized sphere)
    dict(name="External", roi=1, shape="cylinder", radius=100.0,
         center=(0.0, 0.0), z_range=(-100.0, 100.0), hu=0,
         rt_type="EXTERNAL", color=(0, 255, 0), vol_tol_pct=1.0),
    dict(name="PTV", roi=2, shape="sphere", radius=25.0,
         center=(0.0, 0.0, 0.0), hu=40,
         rt_type="PTV", color=(255, 0, 0), vol_tol_pct=2.0),
    dict(name="GTV", roi=3, shape="sphere", radius=10.0,
         center=(0.0, 0.0, 0.0), hu=60,
         rt_type="GTV", color=(255, 128, 0), vol_tol_pct=3.0),
    dict(name="SpinalCord", roi=4, shape="cylinder", radius=5.0,
         center=(0.0, 60.0), z_range=(-100.0, 100.0), hu=40,
         rt_type="ORGAN", color=(0, 0, 255), vol_tol_pct=2.0),
    dict(name="Parotid_L", roi=5, shape="sphere", radius=15.0,
         center=(50.0, -20.0, 20.0), hu=30,
         rt_type="ORGAN", color=(0, 255, 255), vol_tol_pct=2.0),
    dict(name="Cavity_Air", roi=6, shape="sphere", radius=10.0,
         center=(-50.0, -20.0, -20.0), hu=-990,
         rt_type="CAVITY", color=(128, 128, 128), vol_tol_pct=3.0),
]
CENTROID_TOL_MM = 1.0

# Contour polygonization: regular N-gon inscribed in the analytic circle.
# N = 128 keeps the polygon-area deficit at 0.04 % — far inside every
# volume tolerance. Contour coordinates are written as %.5f mm strings
# (deterministic, <= 16-char DS limit, sub-micrometre rounding).
CONTOUR_POINTS = 128

# --- Plan / dose model [OPEN — proposed: 200 cGy x 30 = 60 Gy to PTV;
#     falloff length 50 mm; dose grid 2 x 2 x 2 mm].
PRESCRIPTION_GY = 60.0               # D_p — uniform inside PTV
FRACTIONS = 30
FALLOFF_MM = 50.0                    # D(d) = D_p * max(0, 1 - d/50 mm)
DOSE_GRID_SPACING_MM = 2.0
# Dose grid samples every other CT sample in-plane and every CT slice in z
# ("coincident with the CT grid", subsampled to 2 mm). The one-pixel IPP
# offset in y picks the CT sub-lattice whose sample centers pass closest
# to the SpinalCord's proximal surface (y = 55 mm), which is where the
# analytic SpinalCord D_max lives — minimizing the sampling deficit of a
# tangent-point maximum on a 2 mm grid.
DOSE_ROWS = 128
DOSE_COLS = 128
DOSE_IPP_XY_MM = (-127.5, -126.5)    # (x of col 0, y of row 0)
DOSE_GRID_SCALING = 0.001            # stored uint32 = milligray

# --- DICOM identity [OPEN — org UID root; patient-module values].
# UID root: "2.25." + uuid5(namespace, dataset-version|kind).int — a valid
# UUID-derived root per the spec, deterministic, swap for a registered org
# root by changing UID_NAMESPACE_NAME.
UID_NAMESPACE_NAME = "https://aapm-code-exchange.invalid/phantom-dataset"
# Patient values MUST sit in phi_scan.py's ANON_OK allowlist. The spec's
# proposed "Phantom^CCX" / "CCX-PHANTOM-001" and any populated birth date
# would all be findings, so: name "Phantom", ID "PHANTOM", DOB empty.
PATIENT_NAME = "Phantom"
PATIENT_ID = "PHANTOM"
PATIENT_BIRTH_DATE = ""              # any populated DOB trips phi_scan.py
PATIENT_SEX = "O"
FIXED_DATE = "20260101"              # study/series/content dates
FIXED_TIME = "000000"

# =========================================================================
# End of parameters.
# =========================================================================

SOP_CLASS = {
    "CT": "1.2.840.10008.5.1.4.1.1.2",
    "RTSTRUCT": "1.2.840.10008.5.1.4.1.1.481.3",
    "RTPLAN": "1.2.840.10008.5.1.4.1.1.481.5",
    "RTDOSE": "1.2.840.10008.5.1.4.1.1.481.2",
}
DETACHED_STUDY_MGMT = "1.2.840.10008.3.1.2.3.1"

_UID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, UID_NAMESPACE_NAME)


def make_uid(kind: str) -> str:
    """Deterministic UID: 2.25.<uuid5(dataset-version | kind) as integer>."""
    return "2.25." + str(uuid.uuid5(_UID_NAMESPACE, f"{DATASET_VERSION}|{kind}").int)


UID = {
    "study": make_uid("study"),
    "frame_of_reference": make_uid("frame-of-reference"),
    "ct_series": make_uid("ct-series"),
    "rtstruct_series": make_uid("rtstruct-series"),
    "rtstruct": make_uid("rtstruct-instance"),
    "rtplan_series": make_uid("rtplan-series"),
    "rtplan": make_uid("rtplan-instance"),
    "rtdose_series": make_uid("rtdose-series"),
    "rtdose": make_uid("rtdose-instance"),
    "implementation": make_uid("implementation-class"),
}


def slice_zs() -> list[float]:
    return [CT_Z_FIRST_MM + i * CT_SLICE_THICKNESS_MM
            for i in range(CT_NUM_SLICES)]


def ct_sop_uid(index: int) -> str:
    return make_uid(f"ct-instance-{index:03d}")


# ------------------------------------------------------------------ geometry


def circle_at(struct: dict, z: float) -> tuple[float, float, float] | None:
    """In-plane cross-section of a structure at slice height z.

    Returns (cx, cy, radius) or None if the structure does not intersect
    the plane. Spheres use a strict inequality so degenerate zero-radius
    contours are never emitted.
    """
    if struct["shape"] == "cylinder":
        z0, z1 = struct["z_range"]
        if z0 <= z <= z1:
            cx, cy = struct["center"]
            return cx, cy, struct["radius"]
        return None
    cx, cy, cz = struct["center"]
    h2 = (z - cz) ** 2
    r2 = struct["radius"] ** 2
    if h2 < r2:
        return cx, cy, math.sqrt(r2 - h2)
    return None


def inside_mask(struct: dict, xg: np.ndarray, yg: np.ndarray,
                z: float) -> np.ndarray:
    """Boolean mask of grid points inside the analytic shape at height z."""
    if struct["shape"] == "cylinder":
        z0, z1 = struct["z_range"]
        if not z0 <= z <= z1:
            return np.zeros(xg.shape, dtype=bool)
        cx, cy = struct["center"]
        return (xg - cx) ** 2 + (yg - cy) ** 2 <= struct["radius"] ** 2
    cx, cy, cz = struct["center"]
    return ((xg - cx) ** 2 + (yg - cy) ** 2 + (z - cz) ** 2
            <= struct["radius"] ** 2)


def analytic_volume_cm3(struct: dict) -> float:
    if struct["shape"] == "cylinder":
        z0, z1 = struct["z_range"]
        return math.pi * struct["radius"] ** 2 * (z1 - z0) / 1000.0
    return 4.0 / 3.0 * math.pi * struct["radius"] ** 3 / 1000.0


def analytic_centroid_mm(struct: dict) -> list[float]:
    if struct["shape"] == "cylinder":
        cx, cy = struct["center"]
        z0, z1 = struct["z_range"]
        return [cx, cy, (z0 + z1) / 2.0]
    return list(struct["center"])


def _struct(name: str) -> dict:
    return next(s for s in STRUCTURES if s["name"] == name)


def analytic_spinalcord_dmax_gy() -> float:
    """Closed-form SpinalCord D_max from the falloff model.

    The cord is a vertical cylinder whose z range includes z = 0, so its
    closest approach to the PTV surface is in the z = 0 plane:
    d = (axis distance from origin) - r_cord - r_ptv.
    """
    cord = _struct("SpinalCord")
    ptv = _struct("PTV")
    z0, z1 = cord["z_range"]
    assert z0 <= 0.0 <= z1, "closed form assumes the cord crosses z = 0"
    axis_dist = math.hypot(*cord["center"])
    d = axis_dist - cord["radius"] - ptv["radius"]
    return PRESCRIPTION_GY * max(0.0, 1.0 - d / FALLOFF_MM)


def analytic_integral_dose_gy_cm3() -> float:
    """Closed-form integral dose over External, in Gy * cm^3.

    Valid because the whole nonzero-dose ball (radius r_ptv + falloff)
    sits inside External, so the integral is spherically symmetric:
      D_p * (4/3) pi a^3
        + 4 pi D_p / L * integral_a^b (b - r) r^2 dr,   b = a + L
    with the exact antiderivative used below.
    """
    ext = _struct("External")
    a = _struct("PTV")["radius"]
    b = a + FALLOFF_MM
    z0, z1 = ext["z_range"]
    assert b <= ext["radius"] and b <= min(-z0, z1), \
        "closed form assumes the falloff ball lies inside External"
    core = PRESCRIPTION_GY * 4.0 / 3.0 * math.pi * a ** 3
    shell_integral = (b * (b ** 3 - a ** 3) / 3.0
                      - (b ** 4 - a ** 4) / 4.0)  # = int_a^b (b - r) r^2 dr
    shell = 4.0 * math.pi * PRESCRIPTION_GY / FALLOFF_MM * shell_integral
    return (core + shell) / 1000.0


def dose_gy_at(xg: np.ndarray, yg: np.ndarray, z: float) -> np.ndarray:
    """Analytic dose (Gy) at grid points in the plane at height z."""
    ptv = _struct("PTV")
    ext = _struct("External")
    r = np.sqrt(xg ** 2 + yg ** 2 + z ** 2)
    d_surface = r - ptv["radius"]
    dose = PRESCRIPTION_GY * np.clip(1.0 - d_surface / FALLOFF_MM, 0.0, 1.0)
    dose[r <= ptv["radius"]] = PRESCRIPTION_GY
    z0, z1 = ext["z_range"]
    outside_external = (xg ** 2 + yg ** 2 > ext["radius"] ** 2)
    if not z0 <= z <= z1:
        outside_external |= True
    dose[outside_external] = 0.0
    return dose


# ------------------------------------------------------------------- DICOM


def _base_dataset(modality: str, series_uid: str, series_number: int,
                  series_description: str, with_for: bool = True) -> Dataset:
    ds = Dataset()
    ds.PatientName = PATIENT_NAME
    ds.PatientID = PATIENT_ID
    ds.PatientBirthDate = PATIENT_BIRTH_DATE
    ds.PatientSex = PATIENT_SEX
    ds.StudyInstanceUID = UID["study"]
    ds.StudyDate = FIXED_DATE
    ds.StudyTime = FIXED_TIME
    ds.StudyID = "1"
    ds.AccessionNumber = ""
    ds.ReferringPhysicianName = ""
    ds.StudyDescription = "Synthetic phantom dataset"
    ds.Modality = modality
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.SeriesDescription = series_description
    ds.SeriesDate = FIXED_DATE
    ds.SeriesTime = FIXED_TIME
    ds.Manufacturer = "SYNTHETIC"
    ds.ManufacturerModelName = "generate_phantom.py"
    ds.SoftwareVersions = DATASET_VERSION
    if with_for:
        ds.FrameOfReferenceUID = UID["frame_of_reference"]
        ds.PositionReferenceIndicator = ""
    return ds


def _save(ds: Dataset, sop_class: str, sop_uid: str, path: Path) -> None:
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = sop_uid
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = UID["implementation"]
    meta.ImplementationVersionName = "CCX_PHANTOM"
    ds.file_meta = meta
    ds.save_as(str(path), enforce_file_format=True)


def _fmt(value: float) -> str:
    """Deterministic DS string for contour coordinates (%.5f, <= 16 chars)."""
    return f"{value:.5f}"


def build_ct(out_dir: Path) -> list[str]:
    """Write the CT series; returns the emitted file names in z order."""
    xs = (np.arange(CT_COLS) * CT_PIXEL_SPACING_MM) + CT_IPP_XY_MM[0]
    ys = (np.arange(CT_ROWS) * CT_PIXEL_SPACING_MM) + CT_IPP_XY_MM[1]
    xg, yg = np.meshgrid(xs, ys)  # [row, col] -> (ys[row], xs[col])
    names = []
    for i, z in enumerate(slice_zs()):
        hu = np.full((CT_ROWS, CT_COLS), HU_AIR, dtype=np.int32)
        for struct in STRUCTURES:  # list order: GTV painted after PTV
            hu[inside_mask(struct, xg, yg, z)] = struct["hu"]
        stored = (hu - CT_RESCALE_INTERCEPT).astype("<u2")

        ds = _base_dataset("CT", UID["ct_series"], 1, "Synthetic phantom CT")
        ds.ImageType = ["DERIVED", "SECONDARY", "AXIAL"]
        ds.InstanceNumber = i + 1
        ds.PatientPosition = "HFS"
        ds.ImagePositionPatient = [_fmt(CT_IPP_XY_MM[0]),
                                   _fmt(CT_IPP_XY_MM[1]), _fmt(z)]
        ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
        ds.SliceThickness = _fmt(CT_SLICE_THICKNESS_MM)
        ds.SliceLocation = _fmt(z)
        ds.KVP = "120"
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = CT_ROWS
        ds.Columns = CT_COLS
        ds.PixelSpacing = [_fmt(CT_PIXEL_SPACING_MM),
                           _fmt(CT_PIXEL_SPACING_MM)]
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.RescaleIntercept = str(CT_RESCALE_INTERCEPT)
        ds.RescaleSlope = "1"
        ds.RescaleType = "HU"
        ds.ContentDate = FIXED_DATE
        ds.ContentTime = FIXED_TIME
        ds.PixelData = stored.tobytes()

        name = f"CT_{i:03d}.dcm"
        _save(ds, SOP_CLASS["CT"], ct_sop_uid(i), out_dir / name)
        names.append(name)
    return names


def build_rtstruct(out_dir: Path) -> str:
    zs = slice_zs()
    ds = _base_dataset("RTSTRUCT", UID["rtstruct_series"], 2,
                       "Synthetic phantom structures", with_for=False)
    ds.StructureSetLabel = "PHANTOM"
    ds.StructureSetName = "PHANTOM"
    ds.StructureSetDate = FIXED_DATE
    ds.StructureSetTime = FIXED_TIME
    ds.ApprovalStatus = "UNAPPROVED"

    # Referenced frame of reference -> study -> CT series -> every CT slice.
    contour_image_items = []
    for i in range(CT_NUM_SLICES):
        item = Dataset()
        item.ReferencedSOPClassUID = SOP_CLASS["CT"]
        item.ReferencedSOPInstanceUID = ct_sop_uid(i)
        contour_image_items.append(item)
    series_item = Dataset()
    series_item.SeriesInstanceUID = UID["ct_series"]
    series_item.ContourImageSequence = contour_image_items
    study_item = Dataset()
    study_item.ReferencedSOPClassUID = DETACHED_STUDY_MGMT
    study_item.ReferencedSOPInstanceUID = UID["study"]
    study_item.RTReferencedSeriesSequence = [series_item]
    for_item = Dataset()
    for_item.FrameOfReferenceUID = UID["frame_of_reference"]
    for_item.RTReferencedStudySequence = [study_item]
    ds.ReferencedFrameOfReferenceSequence = [for_item]

    roi_items, contour_items, obs_items = [], [], []
    for struct in STRUCTURES:
        roi = Dataset()
        roi.ROINumber = struct["roi"]
        roi.ReferencedFrameOfReferenceUID = UID["frame_of_reference"]
        roi.ROIName = struct["name"]
        roi.ROIGenerationAlgorithm = "AUTOMATIC"
        roi_items.append(roi)

        contours = []
        for i, z in enumerate(zs):
            section = circle_at(struct, z)
            if section is None:
                continue
            cx, cy, radius = section
            points = []
            for k in range(CONTOUR_POINTS):
                theta = 2.0 * math.pi * k / CONTOUR_POINTS
                points.extend([_fmt(cx + radius * math.cos(theta)),
                               _fmt(cy + radius * math.sin(theta)),
                               _fmt(z)])
            image_item = Dataset()
            image_item.ReferencedSOPClassUID = SOP_CLASS["CT"]
            image_item.ReferencedSOPInstanceUID = ct_sop_uid(i)
            contour = Dataset()
            contour.ContourImageSequence = [image_item]
            contour.ContourGeometricType = "CLOSED_PLANAR"
            contour.NumberOfContourPoints = CONTOUR_POINTS
            contour.ContourNumber = len(contours) + 1
            contour.ContourData = points
            contours.append(contour)
        roi_contour = Dataset()
        roi_contour.ROIDisplayColor = list(struct["color"])
        roi_contour.ReferencedROINumber = struct["roi"]
        roi_contour.ContourSequence = contours
        contour_items.append(roi_contour)

        obs = Dataset()
        obs.ObservationNumber = struct["roi"]
        obs.ReferencedROINumber = struct["roi"]
        obs.ROIObservationLabel = struct["name"]
        obs.RTROIInterpretedType = struct["rt_type"]
        obs.ROIInterpreter = ""
        obs_items.append(obs)

    ds.StructureSetROISequence = roi_items
    ds.ROIContourSequence = contour_items
    ds.RTROIObservationsSequence = obs_items

    name = "RTSTRUCT.dcm"
    _save(ds, SOP_CLASS["RTSTRUCT"], UID["rtstruct"], out_dir / name)
    return name


def build_rtplan(out_dir: Path) -> str:
    ds = _base_dataset("RTPLAN", UID["rtplan_series"], 3,
                       "Synthetic phantom plan")
    ds.RTPlanLabel = "PHANTOM-60GY"
    ds.RTPlanName = "PHANTOM-60GY"
    ds.RTPlanDate = FIXED_DATE
    ds.RTPlanTime = FIXED_TIME
    ds.RTPlanGeometry = "PATIENT"
    ds.ApprovalStatus = "UNAPPROVED"

    ss_ref = Dataset()
    ss_ref.ReferencedSOPClassUID = SOP_CLASS["RTSTRUCT"]
    ss_ref.ReferencedSOPInstanceUID = UID["rtstruct"]
    ds.ReferencedStructureSetSequence = [ss_ref]

    dose_ref = Dataset()
    dose_ref.DoseReferenceNumber = 1
    dose_ref.DoseReferenceStructureType = "VOLUME"
    dose_ref.ReferencedROINumber = _struct("PTV")["roi"]
    dose_ref.DoseReferenceType = "TARGET"
    dose_ref.TargetPrescriptionDose = _fmt(PRESCRIPTION_GY)
    ds.DoseReferenceSequence = [dose_ref]

    beam_ref = Dataset()
    beam_ref.ReferencedBeamNumber = 1
    beam_ref.BeamDose = _fmt(PRESCRIPTION_GY / FRACTIONS)
    beam_ref.BeamMeterset = "200.0"
    fraction_group = Dataset()
    fraction_group.FractionGroupNumber = 1
    fraction_group.NumberOfFractionsPlanned = FRACTIONS
    fraction_group.NumberOfBeams = 1
    fraction_group.NumberOfBrachyApplicationSetups = 0
    fraction_group.ReferencedBeamSequence = [beam_ref]
    ds.FractionGroupSequence = [fraction_group]

    def jaw_item(device_type: str, positions: list[str]) -> Dataset:
        item = Dataset()
        item.RTBeamLimitingDeviceType = device_type
        item.LeafJawPositions = positions
        return item

    cp0 = Dataset()
    cp0.ControlPointIndex = 0
    cp0.NominalBeamEnergy = "6"
    cp0.DoseRateSet = "600"
    cp0.GantryAngle = "0"
    cp0.GantryRotationDirection = "NONE"
    cp0.BeamLimitingDeviceAngle = "0"
    cp0.BeamLimitingDeviceRotationDirection = "NONE"
    cp0.PatientSupportAngle = "0"
    cp0.PatientSupportRotationDirection = "NONE"
    cp0.IsocenterPosition = ["0", "0", "0"]
    cp0.CumulativeMetersetWeight = "0.0"
    cp0.BeamLimitingDevicePositionSequence = [
        jaw_item("ASYMX", ["-30.0", "30.0"]),
        jaw_item("ASYMY", ["-30.0", "30.0"]),
    ]
    cp1 = Dataset()
    cp1.ControlPointIndex = 1
    cp1.CumulativeMetersetWeight = "1.0"

    def limit_item(device_type: str) -> Dataset:
        item = Dataset()
        item.RTBeamLimitingDeviceType = device_type
        item.NumberOfLeafJawPairs = 1
        return item

    beam = Dataset()
    beam.BeamNumber = 1
    beam.BeamName = "AP"
    beam.BeamType = "STATIC"
    beam.RadiationType = "PHOTON"
    beam.TreatmentMachineName = "SYNTH01"
    beam.PrimaryDosimeterUnit = "MU"
    beam.SourceAxisDistance = "1000.0"
    beam.TreatmentDeliveryType = "TREATMENT"
    beam.NumberOfWedges = 0
    beam.NumberOfCompensators = 0
    beam.NumberOfBoli = 0
    beam.NumberOfBlocks = 0
    beam.FinalCumulativeMetersetWeight = "1.0"
    beam.NumberOfControlPoints = 2
    beam.BeamLimitingDeviceSequence = [limit_item("ASYMX"),
                                       limit_item("ASYMY")]
    beam.ControlPointSequence = [cp0, cp1]
    ds.BeamSequence = [beam]

    name = "RTPLAN.dcm"
    _save(ds, SOP_CLASS["RTPLAN"], UID["rtplan"], out_dir / name)
    return name


def build_rtdose(out_dir: Path) -> str:
    zs = slice_zs()
    xs = (np.arange(DOSE_COLS) * DOSE_GRID_SPACING_MM) + DOSE_IPP_XY_MM[0]
    ys = (np.arange(DOSE_ROWS) * DOSE_GRID_SPACING_MM) + DOSE_IPP_XY_MM[1]
    xg, yg = np.meshgrid(xs, ys)
    frames = np.empty((len(zs), DOSE_ROWS, DOSE_COLS), dtype="<u4")
    for i, z in enumerate(zs):
        dose = dose_gy_at(xg, yg, z)
        frames[i] = np.round(dose / DOSE_GRID_SCALING).astype("<u4")

    ds = _base_dataset("RTDOSE", UID["rtdose_series"], 4,
                       "Synthetic phantom dose")
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.InstanceNumber = 1
    ds.ContentDate = FIXED_DATE
    ds.ContentTime = FIXED_TIME
    ds.ImagePositionPatient = [_fmt(DOSE_IPP_XY_MM[0]),
                               _fmt(DOSE_IPP_XY_MM[1]), _fmt(zs[0])]
    ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    ds.SliceThickness = _fmt(CT_SLICE_THICKNESS_MM)
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.NumberOfFrames = len(zs)
    ds.FrameIncrementPointer = pydicom.tag.Tag(0x3004, 0x000C)
    ds.Rows = DOSE_ROWS
    ds.Columns = DOSE_COLS
    ds.PixelSpacing = [_fmt(DOSE_GRID_SPACING_MM),
                       _fmt(DOSE_GRID_SPACING_MM)]
    ds.BitsAllocated = 32
    ds.BitsStored = 32
    ds.HighBit = 31
    ds.PixelRepresentation = 0
    ds.DoseUnits = "GY"
    ds.DoseType = "PHYSICAL"
    ds.DoseSummationType = "PLAN"
    ds.GridFrameOffsetVector = [_fmt(z - zs[0]) for z in zs]
    ds.DoseGridScaling = repr(DOSE_GRID_SCALING)
    plan_ref = Dataset()
    plan_ref.ReferencedSOPClassUID = SOP_CLASS["RTPLAN"]
    plan_ref.ReferencedSOPInstanceUID = UID["rtplan"]
    ds.ReferencedRTPlanSequence = [plan_ref]
    ds.PixelData = frames.tobytes()

    name = "RTDOSE.dcm"
    _save(ds, SOP_CLASS["RTDOSE"], UID["rtdose"], out_dir / name)
    return name


# ------------------------------------------------- reference + verification


def analytic_reference() -> dict:
    """Known-correct outputs computed from the analytic formulas only
    (spec: never from the voxelized data)."""
    structures = {}
    for s in STRUCTURES:
        structures[s["name"]] = {
            "roi_number": s["roi"],
            "shape": s["shape"],
            "volume_cm3": analytic_volume_cm3(s),
            "volume_tolerance_pct": s["vol_tol_pct"],
            "centroid_mm": analytic_centroid_mm(s),
            "centroid_tolerance_mm": CENTROID_TOL_MM,
        }
    return {
        "dataset_version": DATASET_VERSION,
        "generator": "scripts/generate_phantom.py",
        "coordinate_system": "DICOM patient (HFS), mm",
        "structures": structures,
        "dose": {
            "prescription_gy": PRESCRIPTION_GY,
            "fractions": FRACTIONS,
            "falloff_mm": FALLOFF_MM,
            "PTV": {
                "d_mean_gy": PRESCRIPTION_GY,
                "d_min_gy": PRESCRIPTION_GY,
                "d_max_gy": PRESCRIPTION_GY,
                "tolerance_pct": 0.5,
            },
            "SpinalCord": {
                "d_max_gy": analytic_spinalcord_dmax_gy(),
                "tolerance_exact_pct": 2.0,
                "tolerance_voxelized_pct": {"low": -6.0, "high": 0.5},
                "note": ("tangent-point maximum; a 2 mm dose grid "
                         "systematically undersamples it, so the voxelized "
                         "tolerance is asymmetric"),
            },
            "External": {
                "integral_dose_gy_cm3": analytic_integral_dose_gy_cm3(),
                "tolerance_pct": 2.0,
            },
        },
    }


def _polygon_area(xy: np.ndarray) -> float:
    """Shoelace area of a closed planar polygon given as (N, 2) vertices."""
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1))
                           - np.dot(np.roll(x, -1), y)))


def _polygon_mask(xg: np.ndarray, yg: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon test for grid points (crossing number)."""
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


def _read_contours(rtstruct: Dataset) -> dict[str, list[tuple[float, np.ndarray]]]:
    names = {roi.ROINumber: str(roi.ROIName)
             for roi in rtstruct.StructureSetROISequence}
    out: dict[str, list[tuple[float, np.ndarray]]] = {}
    for rc in rtstruct.ROIContourSequence:
        name = names[rc.ReferencedROINumber]
        contours = []
        for c in rc.ContourSequence:
            pts = np.asarray([float(v) for v in c.ContourData]).reshape(-1, 3)
            contours.append((float(pts[0, 2]), pts[:, :2]))
        out[name] = contours
    return out


def achieved_metrics(out_dir: Path) -> dict:
    """Recompute volumes/centroids/dose stats from the EMITTED files, for
    the self-check summary table (generator CI test per spec)."""
    rtstruct = pydicom.dcmread(str(out_dir / "RTSTRUCT.dcm"))
    rtdose = pydicom.dcmread(str(out_dir / "RTDOSE.dcm"))
    contours = _read_contours(rtstruct)

    volumes, centroids = {}, {}
    for name, items in contours.items():
        vol = 0.0
        weighted = np.zeros(3)
        for z, xy in items:
            area = _polygon_area(xy)
            vol += area * CT_SLICE_THICKNESS_MM
            centroid_xy = xy.mean(axis=0)
            weighted += area * np.array([centroid_xy[0], centroid_xy[1], z])
        volumes[name] = vol / 1000.0
        centroids[name] = list(weighted / (vol / CT_SLICE_THICKNESS_MM))

    scaling = float(rtdose.DoseGridScaling)
    dose = rtdose.pixel_array.astype(np.float64) * scaling
    ipp = [float(v) for v in rtdose.ImagePositionPatient]
    spacing = [float(v) for v in rtdose.PixelSpacing]
    offsets = [float(v) for v in rtdose.GridFrameOffsetVector]
    xs = ipp[0] + np.arange(rtdose.Columns) * spacing[1]
    ys = ipp[1] + np.arange(rtdose.Rows) * spacing[0]
    xg, yg = np.meshgrid(xs, ys)
    frame_z = {round(ipp[2] + off, 3): i for i, off in enumerate(offsets)}

    def structure_doses(name: str) -> np.ndarray:
        values = []
        for z, xy in contours[name]:
            frame = frame_z.get(round(z, 3))
            if frame is None:
                continue
            mask = _polygon_mask(xg, yg, xy)
            values.append(dose[frame][mask])
        return np.concatenate(values)

    ptv = structure_doses("PTV")
    cord = structure_doses("SpinalCord")
    voxel_cm3 = spacing[0] * spacing[1] * CT_SLICE_THICKNESS_MM / 1000.0
    return {
        "volumes_cm3": volumes,
        "centroids_mm": centroids,
        "ptv_d_mean_gy": float(ptv.mean()),
        "ptv_d_min_gy": float(ptv.min()),
        "ptv_d_max_gy": float(ptv.max()),
        "spinalcord_d_max_gy": float(cord.max()),
        "integral_dose_gy_cm3": float(dose.sum()) * voxel_cm3,
    }


# ---------------------------------------------------------------- assembly


def _write_json(path: Path, obj: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(out_dir: Path) -> dict:
    """Generate the full dataset into out_dir; returns the manifest dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = build_ct(out_dir)
    files.append(build_rtstruct(out_dir))
    files.append(build_rtplan(out_dir))
    files.append(build_rtdose(out_dir))
    _write_json(out_dir / "reference_values.json", analytic_reference())
    files.append("reference_values.json")
    manifest = {
        "dataset_version": DATASET_VERSION,
        "files": {name: _sha256(out_dir / name) for name in sorted(files)},
    }
    _write_json(out_dir / "manifest.json", manifest)
    return manifest


def print_summary(out_dir: Path) -> None:
    ref = analytic_reference()
    got = achieved_metrics(out_dir)
    rows = []
    for s in STRUCTURES:
        name = s["name"]
        expected = ref["structures"][name]["volume_cm3"]
        actual = got["volumes_cm3"][name]
        rows.append((f"{name} volume [cm^3]", expected, actual,
                     f"+/-{s['vol_tol_pct']:g}%"))
    dose_ref = ref["dose"]
    rows.append(("PTV D_mean [Gy]", dose_ref["PTV"]["d_mean_gy"],
                 got["ptv_d_mean_gy"], "+/-0.5%"))
    rows.append(("PTV D_min [Gy]", dose_ref["PTV"]["d_min_gy"],
                 got["ptv_d_min_gy"], "+/-0.5%"))
    rows.append(("PTV D_max [Gy]", dose_ref["PTV"]["d_max_gy"],
                 got["ptv_d_max_gy"], "+/-0.5%"))
    rows.append(("SpinalCord D_max [Gy]", dose_ref["SpinalCord"]["d_max_gy"],
                 got["spinalcord_d_max_gy"], "-6%/+0.5%"))
    rows.append(("External integral dose [Gy cm^3]",
                 dose_ref["External"]["integral_dose_gy_cm3"],
                 got["integral_dose_gy_cm3"], "+/-2%"))

    print(f"\n{DATASET_VERSION}: analytic reference vs achieved "
          "(recomputed from emitted DICOM)")
    header = (f"  {'Quantity':<34} {'Analytic':>12} {'Achieved':>12} "
              f"{'Diff':>8}  Tolerance")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for label, expected, actual, tol in rows:
        diff_pct = (actual - expected) / expected * 100.0
        print(f"  {label:<34} {expected:>12.3f} {actual:>12.3f} "
              f"{diff_pct:>+7.2f}%  {tol}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output_dir", nargs="?", type=Path,
                    default=Path("data/phantom"),
                    help="output directory (default: ./data/phantom)")
    args = ap.parse_args()

    manifest = generate(args.output_dir)
    print(f"Wrote {len(manifest['files']) + 1} files to {args.output_dir} "
          f"({DATASET_VERSION})")
    print_summary(args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
