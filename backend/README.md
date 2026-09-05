# Settlement Story — Backend

FastAPI implementation of the 2-endpoint API from `settlement_story_build_spec.md`.

## Files

| File | Role |
|---|---|
| `waterfall_core.py` | **Locked.** Copied verbatim from the handoff package. Never edit. |
| `db.py` | SQLite table + seeding from `mock_settlement_data.json` (same fixtures verified in `test_waterfall.py`). |
| `followup.py` | Parses "what if" questions into modified batch inputs. Never computes a waterfall itself. |
| `narrator.py` | Formats an already-computed `WaterfallResult` into plain English. Template-based by default (no API key/network needed); has a clearly-marked `narrate_llm()` stub for wiring in Gemini/Groq later. |
| `main.py` | The FastAPI app — `POST /ask`, `GET /batches`, plus `GET /health`. |

## Run it

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The SQLite DB is created and seeded automatically on startup (`settlement_story.db`, git-ignored — delete it any time to reseed from scratch).

## Try it

```bash
curl http://localhost:8000/batches

curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Why did my settlement come in lower than expected?", "batch_id": "batch-001"}'

# Live follow-up, matching the demo script:
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What if my refunds doubled?", "batch_id": "batch-001"}'
```

## What's verified vs. not (be honest with yourself before the demo)

- ✅ Verified in this environment: `db.py` seeding, `followup.py` parsing, `narrator.py` output, and the full request logic (`main._row_to_batch` → `parse_followup` → `compute_waterfall` → `assert_waterfall_invariants` → `narrate`) — all exercised directly against real fixtures and gave correct numbers.
- ⚠️ **Not verified here:** the actual FastAPI/uvicorn HTTP layer (route decorators, request/response validation, CORS). This sandbox has no network access to install `fastapi`/`uvicorn`, so `main.py` is syntax-checked but has never actually served a request. **Run it locally and hit the endpoints above before you trust it on stage.**

## Follow-up question parser — what it currently understands

`followup.py` is intentionally simple (regex-based, not an LLM) so it's deterministic and free:
- Multiplier words: "doubled", "tripled", "halved" applied to refunds, gateway fee, GST, or reserve
- Explicit percentages: "what if the gateway fee was 3%"
- Explicit rupee amounts: "what if refunds were 2000"

Anything it doesn't recognize falls through to answering about the batch as-is. If your live demo needs a specific follow-up phrasing, test that exact sentence beforehand — don't discover a parser gap live on stage.

## Wiring in a real LLM narrator (optional, post-hackathon)

`narrator.narrate_llm()` is stubbed with the exact contract to follow: pass only the pre-formatted, already-computed numbers into the prompt, instruct the model never to do arithmetic, and fall back to `narrate_template()` on any failure. The build spec recommends using Gemini directly since Antigravity already runs on it — one less API key to manage.

<!-- Deployment trigger: reset database to clean 12 fixtures -->
