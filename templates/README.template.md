# [Tool Name]

<!-- Tier 1 requirement R1.1: purpose, install, worked example. -->

## Purpose

One paragraph: what problem this solves, for whom, and what it is NOT for.
Tier C submissions: this section must include the intended-use statement
(RC.5) and the versioned-use statement (RC.3).

## Installation

Exact steps from a fresh environment. Pin versions (R1.4).

```bash
pip install -r requirements.txt   # or dotnet build, etc.
```

For ESAPI tools: state tested Eclipse/ESAPI versions here (R2.4) and note
that VMS.TPS assemblies are referenced from the local Eclipse install —
never committed.

## Worked example

A stranger must be able to run this end-to-end with the bundled data (R1.5).

```bash
python run_example.py --input example_data/
# Expected output: ...
```

## Testing

(Tier 2) How to run the test suite. What CI runs.

## Validation & commissioning

(Tier C only) Link the validation dataset, expected outputs with tolerances
(RC.1), and the site-commissioning checklist (RC.2).

## Citation

See CITATION.cff. DOI: [badge]

## License

[SPDX id]. See LICENSE.
