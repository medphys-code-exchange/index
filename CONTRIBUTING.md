# Contributing a tool

**The full contributor guide lives in its own repo:
[Contributing-To-The-Community](https://github.com/medphys-code-exchange/Contributing-To-The-Community).**
Start there — it covers repository hygiene (no PHI, no vendor binaries), the
tier requirements, licensing, IP and DCO sign-off, the pre-submission
self-check, and what review looks like.

This page is the two-minute version.

1. **Get your repo safe first.** No PHI, ever — not in the tree, not in
   history, not in a private repo you plan to make public. Use the PHI Scan
   desktop app and the step-by-step guide in
   [brianmanderson/CreatingGithubRepoInstructions](https://github.com/brianmanderson/CreatingGithubRepoInstructions).
   Never commit vendor assemblies (`VMS.*.dll`, RayStation DLLs); reference
   them from the local install and declare your tested platform versions.
2. **Pick a tier** — Tier 1 (research), Tier 2 (rigorous), Tier C
   (clinical-adjacent). Requirements: [docs/tiers.md](docs/tiers.md).
3. **Ship a `LICENSE` (OSI-approved) and a `CITATION.cff`.** Apache-2.0 is
   recommended for new code; copyleft is accepted but flagged.
   ([docs/licensing.md](docs/licensing.md))
4. **Attest, then sign going forward** — your existing history does not need
   signing (R-11); post the submission-time attestation in your intake issue,
   then use `git commit -s` from that day on. Read
   [docs/ip_guidance.md](docs/ip_guidance.md) first: most physicists have never
   checked whether their employer owns work-scope code, and the page gives you
   the two-sentence email for your tech-transfer office.
5. **Run the submission scanners** until both exit 0:
   ```bash
   python scripts/phi_scan.py .
   python scripts/vendor_binary_scan.py .
   ```
6. **Submit** — open a **Tool Submission** issue using the intake form
   ([.github/ISSUE_TEMPLATE/submission.yml](.github/ISSUE_TEMPLATE/submission.yml)).
   No DOI needed up front; it is minted at acceptance for Tier 2 and Tier C.
   Tier 2/C submissions need a tagged release matching the submitted commit.

**What happens next:** automated checks run first and review does not start
until they pass. An editor assigns reviewers, and review happens **publicly in
your issue thread**, driven by the tier checklist in [review/](review/). Target
turnaround is 30 days. On acceptance we record the reviewed commit, cut the
frozen fork, mint the DOI, publish your badged index entry, and name your
reviewers.

Accepted contributors become eligible reviewers — that's how the pool scales.
