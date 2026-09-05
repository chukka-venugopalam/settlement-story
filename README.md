# Settlement Story

**"Why did my settlement come in lower than expected?"** — answered with the exact fee/GST/reserve waterfall, in plain English plus a visual breakdown. Built for Razorpay's AI Buildathon, Track 4 (AI Finance Controller).

> The LLM never computes a number. It only narrates the output of a locked, tested calculation. That's the entire trust proposition — see [Design principles](#design-principles) below.

## Quickstart

```bash
git clone <this-repo>
cd settlement-story
./run.sh
```

Then open http://localhost:8000 in your browser.

That's it — `run.sh` creates a virtualenv, installs backend dependencies, re-runs the locked waterfall tests as a sanity check, then starts a single unified server on port 8000 that serves both the API and the frontend. The frontend's API calls are relative (same-origin), so everything works seamlessly.

**Note:** `run.sh` needs internet access to `pip install fastapi uvicorn pydantic` the first time it runs. Everything downstream of that (the actual math, the API logic, the UI) has already been verified without network access — see [What's been verified](#whats-been-verified-vs-not) below.

### Manual run (if you'd rather not use the script)

```bash
# Single terminal — backend + frontend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open `http://localhost:8000`.

### Pre-Pitch Reset (Clean Demo State)

Right before presenting your demo or pitch, reset the database back to the original 12 seeded fixtures and remove any uploaded test PDFs with a single command:

```bash
python backend/reset_db.py
```

This clears `backend/settlement_story.db`, reseeds the 12 verified fixture batches, and runs the full waterfall invariant test suite to guarantee 100% test passing.

## Deployment (Split Architecture: Render + Vercel)

The repository is configured for split deployment:
- **Backend API**: Python FastAPI on **Render** (root directory `backend/`)
- **Frontend & Landing**: Static HTML on **Vercel** (repo root `.`, routed via `vercel.json`)
- **Local Dev**: `./run.sh` continues to work with zero configuration changes.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full setup instructions, Render blueprint configuration (`render.yaml`), and details on Render's ephemeral SQLite storage behavior.

## What it looks like

Ask "Why did my settlement come in lower than expected?" and you get a top-to-bottom waterfall: **Gross → Gateway fee → GST on fee → Refunds → Reserve held → Net settled**, each band sized proportional to its share of the gross amount, animating in with a soft settling motion. Ask a live follow-up — "What if my refunds doubled?" — and the same real calculation re-runs against the modified input, with a small "Live follow-up" badge marking that it's a hypothetical. The narration above the chart is one paragraph of plain English generated purely by formatting the already-computed numbers.

Ask a forward-looking question like "If I make ₹80,000 in sales today, what would I actually receive?" and it projects what you'd settle using your recent average fee, refund, and reserve rates — still the same locked calculation, just with different inputs.

If something in a batch stands out vs. your recent history (e.g., chargeback reserve 3x higher than usual), a small callout appears above the waterfall to flag it.

Full visual language (colors, type, layout rationale) is documented in [`docs/settlement_story_build_spec.md`](docs/settlement_story_build_spec.md).

## Repo structure

```
settlement-story/
├── run.sh                          One-command unified dev script (backend + frontend on :8000)
├── backend/                        FastAPI app (also serves frontend as static files)
│   ├── main.py                     POST /ask, GET /batches, GET /insights/{batch_id}, GET /, GET /static
│   ├── waterfall_core.py           LOCKED — the only place money is computed
│   ├── db.py                       SQLite seeding + lookups
│   ├── followup.py                 Parses "what if" questions + projection questions into modified inputs
│   ├── narrator.py                 Formats computed results into plain English
│   ├── insights.py                 Compares batch against historical average; flags anomalies
│   ├── mock_settlement_data.json   10 pre-verified settlement fixtures (extended from original 4)
│   ├── test_waterfall.py           Proves waterfall_core.py against the fixtures
│   ├── requirements.txt
│   └── README.md                   Backend-specific details, endpoint examples
├── frontend/
│   ├── index.html                  Single-file UI, no build step. Mounted at / on the backend server
│   └── README.md                   Frontend-specific details, accessibility notes
├── extraction/                     Proof-of-concept: messy PDF → structured data
│   ├── extract_from_pdf.py
│   └── scattered_settlement_statement.pdf
└── docs/
    ├── settlement_story_build_spec.md    Master spec — architecture, design system, demo script
    └── settlement_story_handoff.md       Original project handoff notes
```

## API

| Endpoint | What it does |
|---|---|
| `GET /` | Serve index.html (the UI) |
| `GET /batches` | List available settlement batches (id, label, date, gross amount) |
| `POST /ask` | `{question, batch_id?}` → waterfall breakdown + plain-English narration. If `batch_id` is omitted, the question is treated as a projection (e.g. "if I make ₹80k today...") and computed using average historical rates. If the question is a "what if" hypothetical, the response's `is_hypothetical` field is `true` and `modification_note` explains what was changed. |
| `GET /insights/{batch_id}` | Compare a batch's rates against historical average; return a plain-text flagged observation if something stands out (e.g. "chargeback reserve this batch was 3x your recent average"), or `null` if within normal ranges. |
| `GET /health` | Liveness check |

Full request/response examples in [`backend/README.md`](backend/README.md).

## Design principles

These were decided deliberately and shouldn't be relitigated without a reason:

1. **The LLM never computes a number.** `narrator.py` only formats fields already produced by `waterfall_core.compute_waterfall()`. Follow-up "what if" questions (`followup.py`) only ever produce new *inputs* — the same locked function runs either way, and `assert_waterfall_invariants()` re-checks its own output every time.
2. **Insights never invent figures.** `insights.py` only compares numbers already stored (input rates, amounts) or already computed (waterfall outputs) — it never derives new financial figures. A flagged observation is a ratio (e.g. "3x your average") backed by simple arithmetic, not a prediction.
3. **Projections use the same locked calculation.** A projection question like "if I make ₹80k today" returns a waterfall run on that hypothetical gross amount with average historical rates — still `compute_waterfall()`, just different inputs. The rates themselves are averages of observed historical data, never a guess.
4. **Every currency figure renders in IBM Plex Mono, tabular figures on.** Makes columns of money read as exact instead of approximate.
5. **Why not just paste a statement into ChatGPT:** structured data instead of inference from a static PDF; guaranteed deterministic math; a live connection that supports follow-up questions a one-time upload can't.

## What's been verified vs. not

Built across two sandboxed sessions with no network access, so testing was deliberately layered — real execution wherever possible, honest labeling where not:

| Component | Verified how |
|---|---|
| `waterfall_core.py` | `test_waterfall.py` passes all 4 fixtures — re-run automatically by `run.sh` every time |
| PDF extraction pipeline | Proven to reproduce the exact ₹47,299.70 net-settled figure from a deliberately messy PDF |
| Backend request logic (`db → followup → compute_waterfall → narrate`) | Executed directly against real fixtures, including both hypothetical follow-up scenarios, with output hand-checked against the math |
| Frontend's offline JS math | Extracted and run in Node against the same 4 fixtures — exact match, including both follow-up scenarios cross-checked against the backend's own output |
| WCAG contrast on the color palette | Computed directly (relative luminance / contrast ratio formula) rather than eyeballed — all pairings clear 4.5:1 except Deep Current-on-Deep-Water, which is restricted to large text/badges accordingly |
| **FastAPI/uvicorn HTTP layer itself** | ⚠️ **Not run** — no network in the sandbox to install the packages. Syntax-checked only. |
| **Frontend in an actual browser** | ⚠️ **Not seen rendered** — no display in the sandbox. HTML tag balance and JS syntax checked only. |

**Before you demo:** run `./run.sh`, open the frontend, and click through all three suggested questions at least once. That closes the two gaps above and is also just good practice before a live pitch.

## Track / context

Razorpay AI Buildathon, Track 4 (AI Finance Controller). See `docs/settlement_story_handoff.md` for how this idea was chosen over four other fully-speced alternatives, and `docs/settlement_story_build_spec.md` for the full one-day build schedule and demo script.
