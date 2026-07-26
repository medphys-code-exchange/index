# Reviewer Checklist — Tier 2 (Rigorous)

All of Tier 1, plus the items below. Second reviewer at editor discretion.

## Tier 1 checklist
- [ ] Complete (attach or link the completed Tier 1 checklist)

## Tests
- [ ] Test suite exists and exercises core functionality (not just smoke)
- [ ] CI is green on the exact reviewed commit
- [ ] I ran the tests locally and they pass

## Documentation
- [ ] API/usage docs beyond the README exist and match current behavior
- [ ] Platform matrix declared (runtime versions; vendor versions for
      vendor-API code)

## Release
- [ ] Tagged release exists matching the reviewed commit
- [ ] Reviewed commit SHA == release tag commit: `________`

The Zenodo DOI is **not** a reviewer item: per clarification R-3 it is minted
at acceptance and back-filled into CITATION.cff. See the editor checklist
below.

## Recommendation
- [ ] Accept  /  - [ ] Minor revisions  /  - [ ] Reject

Reviewer: @________   Date: ________

---

## Editor post-acceptance checklist (Tier 2/C — after "Accept")
- [ ] Frozen fork cut at the reviewed commit, banner pointing to the live repo
- [ ] No `.zenodo.json` in the frozen fork — if present it overrides
      `CITATION.cff` entirely and the DOI record will not match the reviewed
      citation file (R-12)
- [ ] Fork **enabled in Zenodo BEFORE tagging** — enabling is not
      retroactive, so a tag pushed first is never archived (R-12)
- [ ] Zenodo DOI minted from the frozen fork's tagged release (R-3)
- [ ] **Version** DOI recorded in the index entry (`entries/<tool>.yml`) —
      it pins the exact reviewed release (R-12)
- [ ] **Concept** DOI back-filled into the author's `CITATION.cff` via PR to
      the live repo — it tracks their newest version and stays correct (R-12)
- [ ] Index entry published; badge shows verified date + platform versions

Editor: @________   Date: ________
