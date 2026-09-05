# Settlement Story — Frontend

Single-file, no build step (`index.html`). Implements the spec's design system exactly: Deep Water / Shallow Water / Ledger Paper / Settling Gold / Receding Coral / Deep Current palette, Fraunces + IBM Plex Sans + IBM Plex Mono type, and the "settling" band-drop animation (each deduction band animates in top-to-bottom with a soft overshoot, staggered ~130ms apart, finishing on the gold net-settled band).

## Run it

Just open `index.html` in a browser — or serve it:

```bash
python3 -m http.server 5500
```

It talks to the backend at `http://localhost:8000` by default (see the `API_BASE` constant near the top of the `<script>` block — change it if you deploy the API elsewhere). Make sure the backend's CORS is permissive enough for wherever you serve this from (it already is, per `main.py`).

## Offline preview mode

If it can't reach the API, the page falls back to bundled demo data and computes the waterfall client-side — a byte-for-byte JS mirror of `waterfall_core.py`'s rounding, **verified in this environment against all 4 fixtures** (see verification note below). A banner appears so it's never silently wrong about which mode it's in. This is a convenience for previewing the UI standalone; **the live demo should always run against the real backend**, not this fallback.

## What's in the UI

- **Batch picker** — pulls from `GET /batches`, defaults to the first one.
- **Chat input + suggested questions** — matches the demo script's three questions (why lower, refunds doubled, fee at 3%).
- **Waterfall funnel** — bands sized proportional to their share of the gross amount; deductions in Receding Coral, net settled in Settling Gold with the largest type treatment on the page.
- **Live follow-up badge** — a small "Live follow-up" pill appears whenever the question triggered a hypothetical (`is_hypothetical: true` from the API), so it's visually obvious a judge's what-if question actually changed the inputs.
- **Narration card** — Ledger Paper surface (the one light panel on an otherwise dark page), Fraunces headline for the opening sentence, Plex Sans body for the rest.

## Accessibility

- All text/background pairings were checked against WCAG contrast math before committing to the palette (see the conversation this was built in) — every pairing used clears 4.5:1, except Deep Current text on Deep Water, which clears only the 3:1 large-text threshold, so it's used exclusively at 15px+/badge weight, never for small body text.
- `prefers-reduced-motion: reduce` disables the settling animation entirely.
- Keyboard: Enter in the question field triggers Ask.

## What's verified vs. not

- ✅ Verified in this environment: the offline JS waterfall math and follow-up parser were extracted and run in Node against the same 4 fixtures used by `test_waterfall.py` — exact match, including the ₹47,299.70 base case and the "refunds doubled"/"fee at 3%" hypotheticals (cross-checked against the backend's own Python simulation of the same questions).
- ⚠️ **Not verified here:** actual rendering in a real browser (this sandbox has no browser/display), and the live fetch path against a running backend (no network in this sandbox). Open `index.html` next to a running `uvicorn main:app` and click through the three suggestion chips before trusting it on stage.
