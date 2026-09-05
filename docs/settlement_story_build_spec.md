# Settlement Story — Build Spec (Track 4: AI Finance Controller)

## Architecture

```
┌──────────────┐      ┌────────────────────┐      ┌──────────────────────┐
│   Frontend    │ ───► │   Backend (API)     │ ───► │  Waterfall calculator   │
│  Chat input   │      │   FastAPI/Express   │      │  (pure functions)       │
│  Waterfall    │ ◄─── │   + LLM narrator     │ ◄─── │  Groq/Gemini call        │
│  chart        │      └──────────┬───────────┘      └──────────────────────┘
└──────────────┘                  │
                                   ▼
                        ┌────────────────────┐
                        │     SQLite DB        │
                        │  Settlement batches   │
                        │  (synthetic)          │
                        └────────────────────┘
```

## Data model

```
SettlementBatch
  id                        uuid pk
  date                      date
  gross_amount               float
  gateway_fee_pct            float   -- e.g. 2%
  gst_on_fee_pct              float   -- 18% GST charged on the fee itself
  refunds_amount              float
  chargebacks_reserve_pct     float   -- rolling reserve held back
```

## The waterfall — the actual product, computed, never guessed

**This logic now lives in its own locked file: `waterfall_core.py`, verified against `mock_settlement_data.json` via `test_waterfall.py` (all 4 fixtures pass — run it yourself before you trust it, don't take this document's word for it). Copy that file into the project exactly as-is; do not let an agent regenerate this function from a prompt, since even a "cleaner-looking" rewrite can silently change the rounding or the order of operations. The version below is kept here for reference only — the `.py` file is the source of truth.**

```python
def compute_waterfall(batch):
    gateway_fee = round(batch.gross_amount * batch.gateway_fee_pct, 2)
    gst_on_fee = round(gateway_fee * batch.gst_on_fee_pct, 2)
    after_fees = round(batch.gross_amount - gateway_fee - gst_on_fee, 2)
    after_refunds = round(after_fees - batch.refunds_amount, 2)
    reserve_held = round(after_refunds * batch.chargebacks_reserve_pct, 2)
    net_settled = round(after_refunds - reserve_held, 2)
    return {
        "gross": batch.gross_amount,
        "gateway_fee": gateway_fee,
        "gst_on_fee": gst_on_fee,
        "refunds": batch.refunds_amount,
        "reserve_held": reserve_held,
        "net_settled": net_settled,
    }
```

The rounding on every line matters — without it, floating-point math can produce a number like `47299.699999999996` live on stage, which reads as broken even though it's technically correct.

The LLM's only job is narrating this dictionary in plain English and answering follow-ups about it — it never computes a number itself. LLMs are unreliable at arithmetic; a judge asking a live money question and getting the wrong number back would kill this demo in one second.

## Why not just upload the PDF to Claude or ChatGPT

Real objection — answer it in the pitch before a judge raises it. If "we're a chatbot too" is the whole answer, the idea is dead, since a general chatbot is already in every merchant's pocket. The real gap is elsewhere:

- A general chatbot is **guessing** at Razorpay's specific fee/GST/reserve structure from whatever a static PDF happens to show. Most settlement PDFs don't cleanly itemize gateway fee, GST-on-fee, refunds, and reserve separately — the chatbot fills that gap with inference, which can be wrong.
- A general chatbot does the **arithmetic itself** on request — the exact failure mode this spec already avoids. This tool never lets the LLM touch a number; it only narrates the pure function's output.
- A PDF upload is a **one-time snapshot**. It can't answer "what if my refunds double next week" against live data — there's no ongoing connection, just whatever was pasted in once. This tool is connected (or, for the demo, simulates being connected) to the underlying structured data directly.

Pitch line: *"You could upload a PDF to ChatGPT and hope the math is right. We connect to the real transaction data and guarantee it."*

## API

```
POST /ask         { question: string, batch_id: uuid } -> narrated answer + waterfall breakdown
GET  /batches      list of synthetic settlement batches, for the demo picker
```

## UI screens

1. **Chat/question box** — type or pick a question ("why was my settlement lower yesterday?").
2. **Waterfall chart** — a funnel: gross at the top, each deduction as a labeled step down to net settled at the bottom.
3. **Live follow-up** — the chat stays open below the chart, so a judge can ask "what if my refunds doubled?" and watch the same real function re-render with new inputs.

## Visual design system

Checked against current Awwwards fintech nominees, Dribbble's 2026 selects, and dashboard-design research (Mercury, Stripe, Plaid) before settling on anything — then made specific to this product's own concept, not a generic fintech template.

**The signature idea:** the waterfall doesn't just render, it settles. Each deduction band drops into place top to bottom with a soft physics-based ease — a slight overshoot, then settle, like a coin landing in a jar — finishing on the net-settled band in gold. One deliberate motion moment; everything else on the page stays still.

**Color** (named, each tied to the settling metaphor, not decorative):

| Name | Hex | Use |
|---|---|---|
| Deep Water | `#12172A` | Page background — the water the money settles through |
| Shallow Water | `#1B2238` | Cards, panels, one layer up |
| Ledger Paper | `#F5F6FA` | The "show the math" panel — cool paper white |
| Settling Gold | `#D4A537` | Net settled figure, primary actions |
| Receding Coral | `#A8503D` | Every deduction band — fees, GST, refunds, reserve |
| Deep Current | `#2B8570` | Secondary accent, links, the live follow-up state |

This deliberately avoids the two most common AI-generated defaults right now: warm cream + terracotta, and near-black + neon. Dark navy itself is common in current fintech design — the real differentiator is warm gold and muted coral instead of navy+neon or navy+bright-orange, with the palette's meaning tied directly to the waterfall instead of used decoratively.

**Typography** — the IBM Plex superfamily, independently validated by current dashboard-typography research as built specifically for data-legible interfaces, free and open-source:
- **Fraunces** (display) — the narrated headline answer, used once, restrained everywhere else
- **IBM Plex Sans** (interface) — labels, questions, body text
- **IBM Plex Mono** (data) — every currency figure, everywhere, tabular figures on, no exceptions — this is what makes columns of money align and read as exact instead of approximate

Type scale:
- Headline: Fraunces, 32/40, weight 500
- Band label: Plex Sans, 13px, weight 600, uppercase, +0.08em tracking — "GATEWAY FEE," "GST ON FEE"
- Body: Plex Sans, 15/22, weight 400
- Net settled figure: Plex Mono, 28px, weight 500, tabular-nums
- Inline band figures: Plex Mono, 16px, weight 400, tabular-nums

**Layout — the waterfall is the page, not a chart inside one:**
```
Settlement Story
"Ask about any settlement"
┌───────────────────────────────┐
│ Why did I get ₹47,300 instead   │
│ of ₹50,000?                      │
└───────────────────────────────┘

GROSS                      ₹50,000
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
GATEWAY FEE                  −₹1,000
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
GST ON FEE                      −₹180
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
REFUNDS                      −₹1,200
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
RESERVE HELD                    −₹320
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

NET SETTLED                 ₹47,300
████████████████████████████████
```
Each band's width is proportional to its amount — the shrinking bars are the argument, before a judge reads a single number.

**Components:**
- Buttons: solid gold fill for the primary "Ask" action, 8–10px corner radius — rounded enough to feel modern, not so rounded it reads as a generic SaaS pill
- Cards: Shallow Water surface, 1px border one shade lighter, no shadow except a soft glow on the currently-animating band
- Chat input: a plain bordered field, muted-gray Plex Sans placeholder — it's a question box, not a decorative search bar
- Chart primitives: Tremor (free, Tailwind-based, the current standard open-source library for custom fintech dashboards) is worth checking for a bar base to adapt — the settling animation on top is custom regardless

**One practical check:** run the palette through WebAIM's free contrast checker before the demo — Plex Mono at 16px on Deep Water needs to clear 4.5:1 contrast. Two minutes, and it's the kind of thing hackathon UIs usually skip.

## Free stack

The waterfall logic is pure Python — zero dependencies, zero risk of being wrong. Groq/Gemini only narrates already-computed numbers. Chart.js or Recharts for the funnel visualization.

## What not to build

Don't attempt a real Razorpay settlement API connection — that needs a live merchant account and real auth. Use synthetic batches modeled on Razorpay's actual published fee structure instead. Never let the LLM touch the arithmetic.

## Demo script

- **0:00–1:00** — the hook: every merchant has stared at a settlement report confused. Pick a real synthetic batch.
- **1:00–2:30** — ask the question live, watch the waterfall render step by step.
- **2:30–4:00** — take a live follow-up from a judge and re-render instantly.
- **4:00–5:00** — close on support-ticket reduction — this is a cost-savings pitch as much as a product pitch.

## Rank #1 checklist

- [ ] Every number in the waterfall comes from the pure function, never the LLM
- [ ] The fee/GST/reserve structure mirrors Razorpay's real published rates
- [ ] A judge's live, unrehearsed follow-up question re-renders correctly
- [ ] No visible lag between question and chart

## One-day build schedule — Google Antigravity

Genuinely achievable in one focused day. The reason: this spec already hands over the exact schema, the exact `compute_waterfall()` code, and an exact 2-endpoint API contract — precisely the unambiguous input an agentic IDE needs to move fast instead of guessing. One note first: Antigravity isn't a VS Code plugin, it's its own VS Code-like app built on Gemini 3 — you'll live inside it, not switch between two tools. Keep plain VS Code around only for a quick manual edit if the agent gets stuck.

**Morning (2.5 hrs) — data layer + the one function that has to be perfect**
- Open a fresh project folder in Antigravity, paste this entire spec into its Planning Mode as the brief.
- Review the generated task plan once, approve it, then let it run — don't babysit every step.
- Let it scaffold the SQLite table, the waterfall function, and 3-4 synthetic settlement batches.
- Hand-calculate one batch yourself and check it against the output. Don't skip or delegate this one step — it's the entire credibility of the demo.

**Midday (2 hrs) — the 2 endpoints**
- Have it build `POST /ask` and `GET /batches` exactly as specified above.
- Antigravity already runs on Gemini 3 — use Gemini directly for the narration call instead of adding Groq as a second provider. One less API key to manage on a one-day build.
- Spot-check the code itself to confirm the narration path never touches the actual numbers — don't just trust the output.

**Afternoon (2 hrs) — UI, tested by the agent itself**
- Build the chat box and waterfall chart screens.
- Use Antigravity's browser-testing feature here specifically — let it click through "ask a question → watch the chart render" itself and produce a recording. This is exactly the task that feature is built for, and it catches broken states before you do.

**Evening (1 hr) — seed data, rehearse, stop**
- Load the 3-4 pre-built batches so the demo never opens on an empty screen.
- Run the demo script above twice, once with a question you make up on the spot.
- Stop there — polishing past this point has low return on a one-day timeline.
