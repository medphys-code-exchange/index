# Before You Attest: Does Your Employer Own Your Code?

If you wrote your tool as part of your job — on work time, on work equipment,
or within your scope of employment — **your institution very likely owns it**.
This is true at nearly every university and hospital system (e.g., University
of California policy assigns such rights to UC). Signing off on a submission
(DCO) is a legal attestation that you have the right to contribute the code.
Attesting without checking is the most common honest mistake in open source.

The good news: institutions almost always say yes to open-source release. It
costs them nothing, generates cited output, and tech-transfer offices have a
routine process for it. Be honest about what you are asking for: an
OSI-approved license cannot be restricted to non-commercial use — Apache-2.0
explicitly grants commercial rights. If you request approval for something
narrower than the license actually conveys, the sign-off you get back does
not cover the release you are making.

## What to do (15 minutes)

1. Find your institution's technology transfer / innovation office.
2. Send this email:

   > Subject: Open-source release approval — [tool name]
   >
   > I've developed a software tool ([one-sentence description]) in the course
   > of my work and would like to release it under an OSI-approved open-source
   > license ([Apache-2.0]), which permits reuse including commercial reuse —
   > that is what open-source release means. The release is for submission to
   > a peer-reviewed medical physics code index. Could you confirm approval
   > or point me to the required process?

3. Keep the reply. You don't submit it to us — the DCO is your attestation —
   but you want it in your records.

## What signing off actually is

Signing off means the Developer Certificate of Origin (DCO): a
`Signed-off-by: Your Name <your.email@example.com>` line on each commit, which
`git commit -s` adds for you. The line attests that you wrote the
contribution, or otherwise have the right to submit it under the stated
open-source license. It is your personal attestation, not a form we process.

**You do not need to sign your existing history (R-11).** Most tools worth
submitting predate the program, and rewriting history to add trailers would
break every existing clone, fork, and citation. Instead:

1. **Attest once at submission.** Post this in your intake issue, covering
   everything at the commit under review:

   > I have the right to contribute the entire tree at commit `<SHA>` under
   > `<LICENSE>`, and I submit it under the terms of the Developer Certificate
   > of Origin (developercertificate.org).
   > Signed-off-by: Your Name <your.email@example.com>

2. **Sign everything from that day forward** with `git commit -s`. A bot
   enforces this on the frozen fork, and it is expected on your live repo.
   If you start a new repo after joining, sign from the first commit.

**No email-domain requirement, but the address must be verified on your GitHub
account.** Gmail, Yahoo, Hotmail, your own domain, your university — all equally
fine, and a non-university address is never grounds for returning a submission.
What is required is that you have added and confirmed that address under GitHub
→ Settings → Emails; an unconfirmed address does not count. GitHub `noreply`
addresses (`12345+user@users.noreply.github.com`) qualify and are the right
choice if you would rather not publish a real one. Quick self-check: open one
of your commits on GitHub — if your avatar and a clickable username appear, the
address is registered to your account.

This is separate from the right-to-release question above (a verified personal
address does not make employer-owned code yours) and from the intake form's
Institution field, which stays required for reviewer-independence checks.

## Special cases

- **Vendor research agreements** (Varian, RaySearch, etc.): code exposing
  non-public API behavior learned under such an agreement cannot be submitted,
  regardless of your institution's approval.
- **Grant-funded code**: federal funding generally *encourages* open release,
  but check the award terms for data/software sharing clauses.
- **Prior employer code**: work you wrote at a previous job belongs to that
  employer. Rewrites from scratch are yours (or your current employer's).
