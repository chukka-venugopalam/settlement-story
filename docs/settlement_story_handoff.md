# Settlement Story — Handoff

Read this first in the new chat. It's written to be self-contained — everything needed to keep building without re-deriving decisions already made.

## What this is

Settlement Story: an AI agent that answers "why did my settlement come in lower than expected" with the full fee/GST/reserve waterfall, in plain English plus a visual breakdown. Built for Razorpay's AI Buildathon, Track 4 (AI Finance Controller).

## Why this idea, specifically

Chosen after a rigorous, weighted comparison against four other fully-speced ideas (Adversarial Dispute Lawyer, Chargeback Immunity, Invisible Insurance, and a later fifth concept called Cashcast), scored on build feasibility, demo power, bar-fit, novelty, market validation, and failure risk. Settlement Story won or tied-for-best on the dimensions that matter most for actually finishing and winning: lowest technical risk, hardest of the group to visibly break on stage, and laser-targeted at a pain Razorpay's own judges have personally lived — confused-merchant settlement support tickets.

## Non-negotiable design principles — do not relitigate these

- **The LLM never computes a number.** It only narrates the output of the locked `compute_waterfall()` function. This is the entire trust proposition of the product. Breaking this breaks the pitch.
- **Every currency figure renders in IBM Plex Mono, tabular figures on.** No exceptions — this is what makes columns of money read as exact instead of approximate.
- **The core answer to "why not just use ChatGPT":** (1) structured data, not inference from a static PDF, (2) guaranteed deterministic math, (3) a live connection that supports follow-up questions a one-time upload can't.

## What's already built and verified — don't rebuild, extend

- `waterfall_core.py` — the locked calculation. Tested: all 4 fixtures in `mock_settlement_data.json` pass via `test_waterfall.py`.
- Razorpay's real fee structure is confirmed by search, not assumed: 2% + 18% GST on domestic cards/UPI/netbanking/wallets; ~3% + GST on EMI/corporate cards/Amex; GST applies to the fee only, never the gross. Already baked into the mock data.
- `scattered_settlement_statement.pdf` + `extract_from_pdf.py` — a full extraction pipeline proven end to end: parses a deliberately messy, realistic PDF statement and reproduces the exact same verified ₹47,299.70 net-settled figure as the clean JSON fixture.
- A complete visual design system (color, type, layout, the "settling" animation concept) grounded in checked current fintech design research — see the build spec's Visual Design System section.
- A full one-day build schedule using Google Antigravity, tied to this exact spec.

## File manifest

- **`settlement_story_build_spec.md`** — the master document. Architecture, schema, API, UI screens, visual design system, free stack, demo script, rank-#1 checklist, one-day build schedule. Start here.
- **`waterfall_core.py`** — the locked, tested calculation. Copy verbatim into the project; never let an agent regenerate it from a prompt.
- **`mock_settlement_data.json`** — 4 test fixtures with pre-verified expected outputs.
- **`test_waterfall.py`** — proves the above two agree. Run it before trusting anything that touches this logic.
- **`scattered_settlement_statement.pdf`** — realistic messy input for testing the extraction layer.
- **`extract_from_pdf.py`** — the extraction pipeline, proven against the PDF above.

## Where things stand

Only the core calculation and the PDF-extraction proof-of-concept are actually built and tested. The API, the UI, and the 5 screens are unbuilt. Next step: follow the one-day schedule in the build spec, starting with feeding the entire spec into Antigravity's Planning Mode as the brief.
