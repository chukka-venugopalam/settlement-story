"""
Settlement Story — narration layer.

CRITICAL INVARIANT: every function here receives an already-computed
WaterfallResult and only ever reads its fields to build sentences. Nothing
in this file performs arithmetic on money. If you wire in an LLM call
(Gemini/Groq per the build spec), the prompt must pass the WaterfallResult
as already-formatted numbers and instruct the model to narrate them
verbatim -- never to recompute or "double check" the math itself.

Two modes:
  - "template" (default): deterministic, offline, zero API calls. Good
    enough for the demo and removes an entire class of live-demo risk.
  - "llm": wired to Gemini, with fallback to template on any failure.
"""

import logging
import os
from waterfall_core import SettlementBatch, WaterfallResult

logger = logging.getLogger(__name__)


def _inr(amount: float) -> str:
    """Format a rupee amount with thousands separators, Indian grouping."""
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    s = f"{amount:,.2f}"
    # Python's comma grouping is Western (lakhs need re-grouping); good
    # enough for the demo's amounts, but note this for the real UI, which
    # should do Indian digit grouping (e.g. 1,00,000) in the frontend layer.
    return f"{sign}₹{s}"


def narrate_template(
    batch: SettlementBatch,
    result: WaterfallResult,
    question: str,
    modification_note: str | None = None,
) -> str:
    lines = []

    if modification_note:
        lines.append(
            f"Here's what your settlement would look like if {modification_note}:"
        )
    else:
        lines.append(
            f"Your settlement of {_inr(result.gross)} on {batch.date} "
            f"came in at {_inr(result.net_settled)} after four deductions."
        )

    lines.append(
        f"Gateway fee took {_inr(result.gateway_fee)} "
        f"({batch.gateway_fee_pct * 100:.1f}% of the gross amount) — "
        f"the fee the payment processor charges for handling the transaction — this is standard on every online payment, not specific to you."
    )
    lines.append(
        f"GST on that fee added another {_inr(result.gst_on_fee)} "
        f"({batch.gst_on_fee_pct * 100:.0f}% of the fee, not the gross) — "
        f"India's tax, but applied only to the fee itself, not your full sale — this trips people up because it's easy to assume tax applies to the whole amount."
    )
    if result.refunds > 0:
        lines.append(
            f"Refunds processed this period totaled {_inr(result.refunds)} — "
            f"money already sent back to customers this period — it's subtracted because it's no longer money you're owed."
        )
    else:
        lines.append(
            "No refunds were processed this period (money already sent back to customers — subtracted only when returns occur)."
        )
    if result.reserve_held > 0:
        lines.append(
            f"A rolling chargeback reserve held back {_inr(result.reserve_held)} "
            f"({batch.chargebacks_reserve_pct * 100:.2f}% of what remained after fees and refunds) — "
            f"a portion held back temporarily as a safety net in case a customer disputes a charge with their bank later — it's not lost, it's released back to you eventually, just not in this settlement."
        )
    else:
        lines.append(
            "No chargeback reserve was held back this period (a portion held back temporarily as a safety net in case a customer disputes a charge with their bank later — released back over time)."
        )

    lines.append(
        f"That leaves a net settled amount of {_inr(result.net_settled)}."
    )

    return " ".join(lines)


def narrate_llm(
    batch: SettlementBatch,
    result: WaterfallResult,
    question: str,
    modification_note: str | None = None,
) -> str:
    """
    Call Gemini to narrate the settlement in plain English.
    
    The prompt contains ONLY already-computed, pre-formatted fields (as strings),
    plus explicit instructions to never perform arithmetic. On ANY failure (timeout,
    API error, empty response), falls back to narrate_template() and logs the error.
    
    Returns: narration string or fallback template output on failure.
    """
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        logger.error("GEMINI_API_KEY not set; falling back to template narration")
        return narrate_template(batch, result, question, modification_note)
    
    # Build prompt with already-computed, pre-formatted numbers as strings
    intro = ""
    if modification_note:
        intro = f"The user modified the settlement as follows: {modification_note}. "
    
    prompt = f"""You are a settlement statement narration assistant for an Indian payment gateway.

{intro}Below is an already-computed settlement waterfall with pre-formatted numbers.
Narrate these numbers in plain English to explain to a merchant what happened to their settlement.

CRITICAL INSTRUCTIONS:
1. Every number you state MUST exactly match the already-computed numbers provided below verbatim.
2. Do not perform arithmetic or calculate new numbers.
3. Do not alter any figure you are given. This is strictly about explanation, not math.
4. Assume the reader has never seen a settlement statement before. Briefly explain what each deduction IS and WHY it exists, in plain language, not just its amount:
   - Gateway fee: the fee the payment processor charges for handling the transaction — this is standard on every online payment, not specific to you.
   - GST on fee: India's tax, but applied only to the fee itself, not your full sale — this trips people up because it's easy to assume tax applies to the whole amount.
   - Refunds: money already sent back to customers this period — it's subtracted because it's no longer money you're owed.
   - Chargeback reserve: a portion held back temporarily as a safety net in case a customer disputes a charge with their bank later — it's not lost, it's released back to you eventually, just not in this settlement.

Settlement date: {batch.date}
Original question from merchant: "{question}"

Already-computed waterfall (in Indian Rupees):
- Gross settlement amount: ₹{result.gross:,.2f}
- Gateway fee ({batch.gateway_fee_pct * 100:.1f}% of gross): ₹{result.gateway_fee:,.2f}
- GST on that fee ({batch.gst_on_fee_pct * 100:.0f}% of the fee): ₹{result.gst_on_fee:,.2f}
- Refunds processed this period: ₹{result.refunds:,.2f}
- Chargeback reserve held ({batch.chargebacks_reserve_pct * 100:.2f}% of amount after fees and refunds): ₹{result.reserve_held:,.2f}
- Net settled amount (after all deductions): ₹{result.net_settled:,.2f}

Narrate this breakdown in clear, conversational language directly answering the merchant's question.
Mention the key numbers exactly as given above and weave in the brief explanations of what each deduction is and why it exists. Do not perform any arithmetic."""

    # 1. Try google.genai SDK (installed modern package)
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        for model_name in ("gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and response.text and response.text.strip():
                    narration = response.text.strip()
                    logger.info(f"LLM narration succeeded via {model_name} (length: {len(narration)} chars)")
                    return narration
            except Exception as e:
                logger.warning(f"Gemini model {model_name} failed: {e}")
    except Exception as e:
        logger.warning(f"google.genai client invocation failed: {e}")

    # 2. Try legacy google.generativeai SDK
    try:
        import google.generativeai as legacy_genai
        legacy_genai.configure(api_key=gemini_key)
        for model_name in ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-1.5-flash"):
            try:
                model = legacy_genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text and response.text.strip():
                    narration = response.text.strip()
                    logger.info(f"LLM narration succeeded via legacy SDK {model_name}")
                    return narration
            except Exception:
                pass
    except Exception:
        pass

    # 3. Direct REST API fallback
    try:
        import json
        import urllib.request
        for model_name in ("gemini-3.5-flash", "gemini-3.6-flash"):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    logger.info(f"LLM narration succeeded via REST API {model_name}")
                    return text
    except Exception as e:
        logger.warning(f"Direct REST API failed: {e}")

    # Final fallback to deterministic template
    logger.warning("All LLM narration paths failed; falling back to template narration")
    return narrate_template(batch, result, question, modification_note)


def narrate(
    batch: SettlementBatch,
    result: WaterfallResult,
    question: str,
    modification_note: str | None = None,
    mode: str = "template",
) -> str:
    if mode == "llm":
        return narrate_llm(batch, result, question, modification_note)
    return narrate_template(batch, result, question, modification_note)

