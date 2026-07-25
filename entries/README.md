# Index entries

One YAML file per submission, named `<tool-slug>.yml` (lowercase, hyphens).
The schema is [templates/submission_metadata.yml](../templates/submission_metadata.yml)
— copy [`_TEMPLATE.yml`](_TEMPLATE.yml) to start a new one. Files beginning
with `_` are ignored by the index builder.

The index page ([../INDEX.md](../README.md)) is **generated** from these files:

```bash
python scripts/build_index.py          # rewrite INDEX.md
python scripts/build_index.py --check   # CI: fail if INDEX.md is stale
```

Status is derived from the data, not stored:

- **Under review** — `verified_date` empty. Listed in the "Under review"
  section with its live repo and review issue.
- **Accepted / listed** — `verified_date` set. Appears in the main index
  table with its badge, license, frozen fork, DOI, and named reviewers.

A field is filled at the stage its schema comment names (intake vs.
acceptance). Do not hand-edit the generated regions of INDEX.md; edit the
entry and re-run the builder.
