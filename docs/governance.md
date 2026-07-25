# Governance and Review Process

## Roles

- **Editor-in-Chief** (Brian Anderson, initially): assigns reviewers, makes
  acceptance decisions, owns the checklists.
- **Co-Lead** (to recruit): full acceptance authority; the program must not
  pause when one person is unavailable.
- **Reviewers**: volunteers drawn initially from recruits, then from accepted
  contributors (acceptance ⇒ reviewer eligibility). Named publicly on every
  review they complete.
- **Contributors**: anyone. Submission requires DCO sign-off and passing
  automated checks.

## Review model (JOSS-style open review)

1. Contributor opens a submission issue using the intake template
   (`.github/ISSUE_TEMPLATE/submission.yml`).
2. Bot runs automated checks (PHI scan, vendor-binary scan, structure lint,
   DCO). Failures are reported in-issue; review does not start until clean.
3. Editor assigns reviewer(s): one for Tier 1/2 (a second Tier 2 reviewer is
   optional at editor discretion), two for Tier C (at least one fully
   independent of the submitting institution — see Conflict of interest).
4. Review happens **publicly in the issue thread**, driven by the tier
   checklist (`review/`). Reviewers check items off, raise concerns as
   comments, and the contributor responds with fixes.
5. On acceptance: editor records commit hash + tier + platform matrix, org
   forks the frozen snapshot; for Tier 2 and Tier C the Zenodo DOI is minted
   at acceptance via the org's Zenodo integration and back-filled into
   `CITATION.cff` and the submission metadata record (Tier 1 receives no
   DOI — index entry + badge only). Index entry + badge go live, reviewers
   are named in the index entry.

## Service levels

- Target turnaround: **30 days** submission → decision. Track and publish it.
- Reviewer WIP cap: **2–3 concurrent reviews**.
- A submission idle 60 days for contributor response is closed as stale
  (resubmission welcome).

## Reviewer credit

Every accepted index entry names its reviewers with links. Review is a
documented, citable professional service activity — this is deliberate and is
part of the incentive model.

## Conflict of interest

The default standard: reviewers do not review submissions from their own
institution or from co-authors/collaborators within the past 4 years (same
standard Brian applies in journal AE work). For Tier C, at least ONE of the
two reviewers must be fully independent of the submitting institution — no
same-institution affiliation, no co-authorship with the submitter within
4 years. The second reviewer may be non-independent, but must disclose the
relationship in the public review issue.

**Recusal:** submissions authored by the Editor-in-Chief or Co-Lead are
editor-handled by the other of the two (or by a designated external editor if
both are conflicted). An author never holds acceptance authority over their
own submission.

**Pilot exception — 2026-07-24, scoped to the DicomRTTool pipeline test.**
Before a co-lead exists, the first end-to-end run uses Brian as author,
reviewer, and editor for the sole purpose of exercising the pipeline mechanics
(intake → scans → checklist → frozen fork → DOI → index entry). The resulting
badge, DOI, and index entry are **pipeline-test artifacts, marked as such**,
and do NOT constitute an independent acceptance. A genuine independent
re-review — by the first recruited co-lead or a designated external editor —
is required before DicomRTTool is presented as independently reviewed. This
exception is one-time and applies to no other submission; R-2 governs in full
for everything external.
