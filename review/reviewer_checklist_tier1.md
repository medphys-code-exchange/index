# Reviewer Checklist — Tier 1 (Research / Analysis)

Copy into the review issue. Check items as verified. One reviewer required.
Automated items should already be green before review starts — spot-check,
don't re-do the bot's work.

## Automated (verify bot status)
- [ ] PHI scan clean
- [ ] Vendor-binary scan clean
- [ ] Submission lint clean. It checks: README, LICENSE, CITATION.cff, a
      dependency manifest exists, every declared dependency carries a version
      relation (no bare names), and no unpinned `git+` reference. It does NOT
      judge whether the relation is *right* for the submission type — that is
      the R1.4 item under Human review.
- [ ] Submission-time DCO attestation posted in the intake issue, covering the
      whole tree at the reviewed commit (R-11). Pre-existing history does NOT
      need `Signed-off-by` — do not return a submission for unsigned history.
- [ ] Any commits made after the submission date carry `Signed-off-by` (R-11
      going-forward rule; nothing to check if there are none yet)
- [ ] Sign-off address is verified on the signer's GitHub account (R-10) —
      **not bot-checked; verify by eye.** On GitHub the commit should show the
      author's avatar and a clickable username; a plain unlinked name means the
      address is not registered to an account. Domain is irrelevant — Gmail and
      Yahoo are fine, unregistered is not. Applies to the attestation's
      address as well as to signed commits.

## Human review
- [ ] README purpose statement is accurate — the code does what it claims
- [ ] I ran the worked example end-to-end from a fresh environment and it
      produced the documented output
- [ ] Bundled example data is synthetic or public; nothing looks like real
      patient data the scanners might have missed
- [ ] **R1.4 dependency style suits the submission type (R-13).** Application
      → exact pins or a lockfile. Library → lower bounds (`>=`) at the oldest
      tested version; an upper bound only where a real incompatibility is
      named, never as blanket caution. Returning a library for "not pinned" is
      a review error.
- [ ] **R1.4 reproducibility record present** for the reviewed commit — the
      resolved versions the suite actually passed against (CI `pip freeze`,
      committed or attached to this issue). Without it the badge's "tested
      against" claim cannot be checked later.
- [ ] Dependencies install cleanly from the declaration; no undeclared
      dependencies surfaced
- [ ] No obvious correctness red flags in a code skim (wrong units, silent
      failure modes, hard-coded local paths)
- [ ] License in LICENSE matches CITATION.cff and README
- [ ] License is OSI-approved (lint verifies the SPDX id against the
      known-OSI list; verify manually if lint flagged it as unrecognized)
- [ ] Reviewed commit SHA recorded: `________`

## Recommendation
- [ ] Accept  /  - [ ] Minor revisions  /  - [ ] Reject

Reviewer: @________   Date: ________
