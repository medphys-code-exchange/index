# Synthetic Phantom Dataset — Requirements Spec (v0.1)

Implements design decision D9: the org-hosted synthetic phantom set
(CT + RTSTRUCT + RTPLAN + RTDOSE) that submissions use as the standard test
target. This is a requirements spec, not the dataset; the generator is a
roadmap Phase 1 deliverable. Parameters marked **[OPEN]** need Brian's
sign-off before generation.

## Purpose

- A single, shared DICOM-RT dataset every submission can test against, so
  results are comparable across tools (D9 reasoning).
- Analytically known geometry and dose, so a tool's output can be checked
  against exact answers, not against another tool.
- Zero PHI **by construction** — every tag value is synthesized; there is no
  patient to de-identify. The dataset must itself pass `scripts/phi_scan.py`
  clean.
- Small enough to vendor into a CI job without LFS or external fetch.
  Size budget: **≤ 50 MB uncompressed [OPEN]**.

## Non-goals

- Not anatomically realistic. No atlas, no template patient, no deformation.
  Realism invites scope creep and adds nothing to correctness testing.
- Not a dosimetric benchmark. The dose is analytically defined, not computed
  by a TPS; it validates dose *handling* (grids, DVHs, interpolation, units),
  not dose *calculation* accuracy.
- Not a substitute for Tier C validation datasets (RC.1) — those are
  tool-specific. This is the common floor.
- Not an imaging-physics phantom (no noise model, no HU calibration curve
  beyond the assigned values).

## Geometry

All coordinates in the DICOM patient coordinate system, mm, HFS orientation.
Origin at the phantom axis center. Analytic shapes only — spheres and
cylinders — so volumes and centroids are closed-form.

Body: water-equivalent cylinder, axis along z.

| Structure     | Shape    | Parameters [OPEN — proposed]                  | HU   |
|---------------|----------|-----------------------------------------------|------|
| External      | cylinder | r = 100 mm, z ∈ [−100, +100]                  | 0    |
| PTV           | sphere   | r = 25 mm, center (0, 0, 0)                   | 40   |
| GTV           | sphere   | r = 10 mm, center (0, 0, 0), concentric in PTV| 60   |
| SpinalCord    | cylinder | r = 5 mm, center (0, +60, ·), z ∈ [−100,+100] | 40   |
| Parotid_L     | sphere   | r = 15 mm, center (+50, −20, +20)             | 30   |
| Cavity_Air    | sphere   | r = 10 mm, center (−50, −20, −20)             | −990 |

Outside External: air (−1000 HU). Structures deliberately exercise the common
cases: concentric containment (GTV ⊂ PTV), a long thin OAR crossing every
slice (SpinalCord), an off-axis laterality structure (Parotid_L), and a
low-density region (Cavity_Air).

CT grid **[OPEN — proposed]**: 256 × 256 pixels, 1.0 × 1.0 mm pixel spacing,
2.0 mm slice thickness, ~110 slices covering z ∈ [−108, +108]. Rationale:
sub-slice structures would make volume tolerances meaningless; full 512
matrix roughly quadruples size for no test value.

## Structure naming (TG-263)

RTSTRUCT ROI names follow TG-263 exactly — this dataset should model the
nomenclature standard the program references. Names as in the table above:
`External`, `PTV`, `GTV`, `SpinalCord`, `Parotid_L`, plus `Cavity_Air`
(non-standard utility structure, prefixed per TG-263 rules if needed
**[OPEN]**). ROI Number assignments are fixed and documented so tools can be
tested on lookup-by-name *and* lookup-by-number.

## Plan and dose

RTPLAN: minimal but valid — a single-beam (or zero-beam "plan shell")
photon plan referencing the RTSTRUCT, prescription 200 cGy × 30 = 60 Gy to
PTV **[OPEN — or a deliberately simple 2 Gy single fraction]**. The plan
exists so RTDOSE has something valid to reference and so plan-parsing tools
have a target; beam parameters are not dosimetrically meaningful.

RTDOSE: grid coincident with the CT grid (same FrameOfReference, same
orientation; grid spacing may be 2 × 2 × 2 mm **[OPEN]**). Dose is
analytically defined, piecewise:

- Inside PTV: uniform **D_p = 60.0 Gy**.
- Outside PTV, inside External: linear falloff with distance d from the PTV
  surface, D(d) = D_p · max(0, 1 − d / 50 mm) **[OPEN — falloff length]**.
- Outside External: 0 Gy.

This makes every DVH metric computable in closed form (or by trivially
convergent numeric integration of the analytic function): PTV D_mean = 60 Gy
exactly, SpinalCord D_max determined by its closest approach to the PTV
surface, etc. The generator must emit the analytic reference values alongside
the DICOM (see next section), computed from the *formulas*, never from the
voxelized dose itself.

## DICOM conformance requirements

- Valid, globally unique UIDs under a registered or UUID-derived (2.25.) org
  root **[OPEN — root]**; UIDs deterministic given the dataset version (see
  Generation) so regeneration is byte-comparable.
- One `FrameOfReferenceUID` shared by CT, RTSTRUCT, RTPLAN, RTDOSE.
- RTSTRUCT `ReferencedFrameOfReferenceSequence` references the CT series;
  every contour references its CT SOP instance.
- RTDOSE `ReferencedRTPlanSequence` references the RTPLAN; RTPLAN
  `ReferencedStructureSetSequence` references the RTSTRUCT.
- Consistent patient module across all four objects: PatientName
  `Phantom^CCX`, PatientID `CCX-PHANTOM-001`, obviously synthetic DOB/dates
  (e.g., 20000101) **[OPEN — exact values; must not trip phi_scan.py's
  realism heuristics]**.
- Files load without error in pydicom and pass a structural validator
  (dciodvfy or equivalent) with no errors **[OPEN — validator choice]**.

## Known-correct outputs

Shipped as `reference_values.json` (or .csv) next to the DICOM, versioned
with it. Minimum contents, all derived analytically:

| Quantity                    | Value (from proposed geometry) | Tolerance [OPEN]     |
|-----------------------------|--------------------------------|----------------------|
| PTV volume                  | 65.45 cm³ (4/3·π·2.5³)        | ± 2 % (voxelization) |
| GTV volume                  | 4.19 cm³                       | ± 3 %                |
| SpinalCord volume           | 15.71 cm³ (π·0.5²·20)         | ± 2 %                |
| Parotid_L volume            | 14.14 cm³                      | ± 2 %                |
| External volume             | 6283.2 cm³                     | ± 1 %                |
| Each structure centroid     | as specified in Geometry       | ± 1 mm               |
| PTV D_mean / D_min / D_max  | 60.0 / 60.0 / 60.0 Gy          | ± 0.5 % / grid-dep.  |
| SpinalCord D_max            | closed-form from falloff       | ± 2 %                |
| External integral dose      | closed-form                    | ± 2 %                |

Two tolerance classes: analytic-vs-voxelized (what a correct tool computing
from the DICOM should hit) and exact (what a tool computing from the analytic
description should hit). The table ships both **[OPEN — final numbers to be
emitted by the generator, not hand-maintained]**.

## Generation

- A single script, proposed `scripts/generate_phantom.py`, pydicom-based,
  stdlib + pydicom + numpy only.
- **Deterministic**: fixed seed, fixed dates, UIDs derived by hashing
  (dataset version, SOP class, instance index) under the org root. Running
  the generator twice at the same version produces byte-identical files.
- The generator lives in the org repo; **the generator is the source of
  truth, the DICOM is a build artifact**. This keeps the dataset auditable
  and reproducible rather than a blob of trusted binaries — consistent with
  the program's own posture on opaque binaries (D5).
- Generator emits: the four DICOM objects, `reference_values.json`, and
  `MANIFEST.sha256` covering every file.
- Generator has its own tests (volumes recomputed from emitted DICOM match
  reference values within tolerance) run in org CI.

## Versioning and distribution

- Semantic version, starting `phantom-v1.0.0`. Any change to geometry, dose,
  tags, or grid is at least a minor bump; anything that changes reference
  values is a major bump.
- Distributed as tagged GitHub releases of the generator repo, each release
  attaching the pre-built dataset zip + `MANIFEST.sha256`. Zenodo DOI per
  release **[OPEN — same Zenodo integration as tool releases]**.
- Submission CI may either download the pinned release by checksum or
  regenerate from the pinned generator tag; templates in
  `templates/workflows/` will reference a pinned version, never "latest".
- Old versions are never deleted (D2 applies to our own artifacts too).

## Acceptance criteria (for the dataset itself)

The dataset is accepted for use as the standard target when:

1. `scripts/phi_scan.py` and `scripts/vendor_binary_scan.py` pass clean on
   the built artifact.
2. Structural DICOM validation passes with zero errors.
3. All four objects load and cross-reference correctly in pydicom and in at
   least two independent consumers (proposed: 3D Slicer + one TPS import
   **[OPEN]**).
4. Independently computed volumes/centroids/DVH stats (i.e., not by the
   generator's own code) match `reference_values.json` within tolerance —
   DicomRTTool is the natural first consumer (D12 stress test).
5. Built artifact ≤ size budget; regeneration is byte-identical at the same
   tag on two different machines.
6. Brian signs off on all **[OPEN]** parameters above.

## Implementation notes (v0.1 generator, 2026-07-23)

`scripts/generate_phantom.py` implements this spec with the proposed [OPEN]
defaults. It is deterministic (fixed dates/UIDs, byte-identical on re-run),
emits `reference_values.json` (analytic) + `manifest.json` (SHA-256), and its
15-test suite recomputes volumes/centroids/dose independently from the
contours and dose voxels. Output is 21.3 MB (within the ≤50 MB budget) and
passes both scanners clean. Two empirical findings need Brian's ruling and
supersede the noted [OPEN] proposals:

- **Patient identity (supersedes the identity [OPEN]).** The proposed values
  `Phantom^CCX` / `CCX-PHANTOM-001` / DOB `20000101` do **not** pass
  `phi_scan.py`: composite names aren't on the ANON_OK allowlist and any
  populated birth date is a finding. The generator ships `Phantom` /
  `PHANTOM` / empty birth date — the ANON_OK-compliant choice. Either bless
  these values in the spec or extend ANON_OK to cover the richer identifiers.
- **SpinalCord D_max tolerance is physically unachievable as written.** The
  ±2% band on the 24 Gy max cannot be met on a 2 mm dose grid: the maximum
  sits at a cylinder tangent point, and best-case voxel sampling yields
  ≈23.39 Gy (−2.6%). Options: a finer dose grid, an interpolated-D_max
  requirement, or a documented voxel-aware asymmetric tolerance (the
  generator currently ships −6%/+0.5% and the test uses that band). Pick one.
- Minor, no ruling needed: 108 slices with odd-mm centers put cylinder end
  caps on slice boundaries (exact volumes); `Cavity_Air` left unprefixed per
  the open TG-263 question; manifest is `manifest.json` (not the spec's
  `MANIFEST.sha256`); `dciodvfy` structural validation still [OPEN] (only
  pydicom validation run so far).
