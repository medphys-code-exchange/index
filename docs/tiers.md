# Submission Tiers

> **Sync obligation.** The contributor-facing rendering of this text lives in
> the `Contributing-To-The-Community` repo, at `docs/02-tiers.md`. The
> requirement IDs and their meaning are normative in both places — never edit
> one without the other.

The badge on the index certifies a specific reviewed commit at a specific
tier. The tier defines what "reviewed" means. Automated checks run before any
human reviewer sees the submission; a submission that fails automated checks
is returned without review.

## Tier 1 — Research / Analysis Tools (light bar)

Intended for: research code, analysis scripts, utilities, prototypes. Not for
anything whose output feeds a clinical decision.

Requirements (all bot-checkable except R1.6):

- **R1.1 README** containing: purpose statement, installation steps, and at
  least one fully worked example a stranger can run end-to-end.
- **R1.2 License** — a `LICENSE` file with an OSI-approved license.
- **R1.3 Citation** — a valid `CITATION.cff` (template provided).
- **R1.4 Declared dependencies** (R-13) — every runtime dependency carries a
  version relation. **A bare name is never acceptable.** Beyond that:
  - **Applications** (anything a user *runs*): exact pins or a lockfile.
  - **Libraries** (anything a user *imports*): a lower bound is required
    (`>=`), set to the oldest version actually tested. Upper bounds are
    permitted but not required — use one only for a known incompatibility,
    never as a default, because routine capping breaks downstream resolution.
    `~=` is acceptable.
  - **Either kind:** direct VCS references pinned to a commit SHA or tag
    (`pkg @ git+https://…` with no revision resolves to whatever the default
    branch holds at install time).
  - **Either kind:** a reproducibility record for the reviewed commit — the
    resolved versions the suite actually passed against. A CI `pip freeze`
    (or `dotnet list package`) on the reviewed commit satisfies it, committed
    or attached to the review issue. The lower bound tells a consumer what
    they may install; only this record tells a reader what was *verified*,
    which is what the badge asserts.
- **R1.5 Runnable example data** — synthetic or public data bundled or
  fetched by the example, sufficient to execute the worked example. No PHI.
- **R1.6 Reviewer sanity pass** — one reviewer confirms the worked example
  runs and the code does what the README claims.
- **R1.7 Automated scans pass** — PHI scan and vendor-binary scan clean.
- **R1.8 DCO** — sign-off is **going-forward, not retroactive** (R-11).
  Pre-existing history does not need signing; instead (a) the author posts a
  submission-time attestation in the intake issue covering the entire tree at
  the reviewed commit, and (b) every commit from the submission date forward
  carries `Signed-off-by` (`git commit -s`). Repos started after joining the
  program sign from their first commit. The address must be verified on the
  signer's GitHub account; any domain qualifies (R-9, R-10).

## Tier 2 — Rigorous (default for mature tools)

Everything in Tier 1, plus:

- **R2.1 Automated tests** — a test suite exercising the core functionality,
  passing in CI on the exact reviewed commit.
- **R2.2 Documentation** — API or usage documentation beyond the README
  (docstrings + generated docs, a `docs/` directory, or equivalent).
- **R2.3 Tagged release; DOI at acceptance** — a tagged release corresponding
  to the reviewed commit must exist at review time. The Zenodo DOI is minted
  at acceptance via the org's Zenodo integration and back-filled into
  `CITATION.cff` and the submission metadata record.
- **R2.4 Platform matrix** — declared tested versions: language runtime,
  key dependencies, and (for vendor-API code) vendor platform versions
  (e.g., Eclipse 18.0 / ESAPI 18.0).
- **R2.5 Second reviewer** — optional at Tier 2, at editor discretion.

## Tier C — Clinical-Adjacent (Tier 2 mandatory + additions)

Applies to any tool whose output could plausibly inform a clinical decision:
plan checks, dose calculations, QA analysis, structure evaluation, transfer
checks. If in doubt, it's Tier C. A Tier C submission that meets only Tier 1
quality is rejected, not down-tiered.

Everything in Tier 2, plus:

- **RC.1 Validation dataset** — bundled input data with known-correct outputs
  and tolerances, such that a site can verify the tool reproduces expected
  results locally.
- **RC.2 Site-commissioning checklist** — a document instructing an adopting
  site what to run and what numbers to confirm before clinical use, in the
  spirit of TPS commissioning practice.
- **RC.3 Versioned-use statement** — README prominently states clinical use
  is only supported from tagged releases, never from `main`.
- **RC.4 Two reviewers** — mandatory; at least ONE must be fully independent
  of the submitting institution (no same-institution affiliation, no
  co-authorship with the submitter within 4 years). The second reviewer may
  be non-independent but must disclose the relationship in the public review
  issue.
- **RC.5 Intended-use statement** — explicit description of what the tool is
  and is not for. This is the reference-implementation framing: local
  commissioning is required; the badge is not a clinical clearance.

## Verification status (all tiers)

Acceptance records: reviewed commit hash, tier, platform matrix, review issue
link, date. The badge displays "Verified [date] — tested against [platform
versions]". If verification is not renewed within 24 months (re-run of
scans + CI on the frozen fork, or author re-attestation with updated
platform matrix), status auto-flips to
"Archived — verified as of [date], unverified since." Nothing is ever deleted.

## Tier promotion

Tier 1 → Tier 2 is a supported path: author requests re-review against Tier 2
requirements; on success the badge and index entry update, and a new frozen
fork is cut at the newly reviewed commit.
