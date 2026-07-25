# Reviewer Checklist — Tier C (Clinical-Adjacent)

Tier 2 is mandatory. TWO reviewers required; at least ONE must be fully
independent of the submitting institution (no same-institution affiliation,
no co-authorship with the submitter within 4 years). The second reviewer may
be non-independent but must disclose the relationship in the public review
issue. Both complete this checklist independently.

## Tier 2 checklist
- [ ] Complete (attach or link)

## Independence

**Reviewer 1** (must be fully independent):
- [ ] I am not at the submitting institution and have no co-authorship with
      the submitter in the past 4 years

**Reviewer 2** (check exactly one):
- [ ] I am not at the submitting institution and have no co-authorship with
      the submitter in the past 4 years
- [ ] I have a relationship with the submitter or submitting institution
      (same institution and/or co-authorship within 4 years), disclosed in
      the review issue as: ________

## Intended use
- [ ] Intended-use statement present, specific, and honest about limitations
- [ ] Versioned-use statement present (clinical use from tagged releases only)
- [ ] Nothing in docs or code implies regulatory clearance or removes the
      site's commissioning responsibility

## Validation package
- [ ] Validation dataset bundled with known-correct outputs AND tolerances
- [ ] I independently ran the validation set and reproduced the expected
      outputs within stated tolerances
- [ ] Site-commissioning checklist is actionable: a physicist at another
      site could execute it without contacting the author
- [ ] Failure behavior reviewed: tool fails loudly, not silently, on bad
      input (spot-checked with malformed/edge-case input)

## Domain correctness
- [ ] Units, coordinate systems, and dose conventions are explicit and
      correct (spot-check against known cases)
- [ ] Structure naming follows TG-263 where applicable

## Recommendation
- [ ] Accept  /  - [ ] Minor revisions  /  - [ ] Reject

Reviewer: @________   Institution: ________   Date: ________
