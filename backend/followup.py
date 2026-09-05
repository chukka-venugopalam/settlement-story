"""
Settlement Story — follow-up question parsing.

Handles the live-demo moment: a judge asks "what if my refunds doubled?"
and the SAME real compute_waterfall() re-renders with adjusted inputs.

This module only ever produces a *new set of inputs* to feed into
compute_waterfall(). It never computes a waterfall number itself -- that
guarantee lives entirely in waterfall_core.py.

Also handles projection questions like "if I make 80000 today, what would
I receive?" -- uses average rates as the baseline and returns a projection
with a note that it's not tied to a specific past batch.
"""

import re
from dataclasses import replace
from typing import Optional

from waterfall_core import SettlementBatch
import db


# Recognized patterns, in priority order. Each maps a regex on the lowercased
# question to a (field_name, transform) pair. transform(current_value, match)
# -> new_value.

_MULTIPLIER_WORDS = {
    "double": 2.0,
    "doubled": 2.0,
    "triple": 3.0,
    "tripled": 3.0,
    "halve": 0.5,
    "halved": 0.5,
    "half": 0.5,
}

_FIELD_ALIASES = {
    "refund": "refunds_amount",
    "refunds": "refunds_amount",
    "fee": "gateway_fee_pct",
    "fees": "gateway_fee_pct",
    "gateway fee": "gateway_fee_pct",
    "reserve": "chargebacks_reserve_pct",
    "chargeback reserve": "chargebacks_reserve_pct",
    "gst": "gst_on_fee_pct",
}


def clean_question(question: str) -> str:
    """Trim leading/trailing whitespace and quote characters (single, double, curly quotes)."""
    if not question:
        return ""
    q = question.strip()
    # Strip leading/trailing quote marks and punctuation artifacts
    quote_chars = '"\'`“”‘’«»'
    q = q.strip(quote_chars).strip()
    return q


def _find_field(question: str) -> Optional[str]:
    # Prefer longer/more specific aliases first (e.g. "gateway fee" before "fee")
    for alias in sorted(_FIELD_ALIASES, key=len, reverse=True):
        if alias in question:
            return _FIELD_ALIASES[alias]
    return None


def _get_average_batch() -> Optional[SettlementBatch]:
    """Create a synthetic batch using average rates across all historical batches."""
    batches = db.list_all_batches()
    if not batches:
        return None
    
    # Use a standard gross amount for projection (e.g., 80k)
    avg_fee_pct = sum(b["gateway_fee_pct"] for b in batches) / len(batches)
    avg_gst = sum(b["gst_on_fee_pct"] for b in batches) / len(batches)
    avg_refund_ratio = sum(b["refunds_amount"] / b["gross_amount"] for b in batches) / len(batches)
    avg_reserve_pct = sum(b["chargebacks_reserve_pct"] for b in batches) / len(batches)
    
    return SettlementBatch(
        id="projection",
        date="2026-08-30",
        gross_amount=80000.0,  # default; will be replaced by user input
        gateway_fee_pct=avg_fee_pct,
        gst_on_fee_pct=avg_gst,
        refunds_amount=80000.0 * avg_refund_ratio,  # will be recalculated
        chargebacks_reserve_pct=avg_reserve_pct,
    )


def parse_followup(question: str, batch: SettlementBatch) -> tuple[Optional[SettlementBatch], Optional[str]]:
    """
    Look for a hypothetical modification in the question text.

    Returns (modified_batch, description) if a modification was detected,
    or (None, None) if the question is just asking about the batch as-is.
    """
    q = clean_question(question).lower()

    if "what if" not in q and "what would happen if" not in q:
        return None, None

    field = _find_field(q)
    if field is None:
        return None, None

    # Case 1: multiplier word ("doubled", "halved", ...)
    for word, mult in _MULTIPLIER_WORDS.items():
        if re.search(rf"\b{word}\b", q):
            current = getattr(batch, field)
            new_value = round(current * mult, 6)
            modified = replace(batch, **{field: new_value})
            label = field.replace("_pct", "").replace("_amount", "").replace("_", " ")
            return modified, f"{label} {word} (from {current} to {new_value})"

    # Case 2: explicit percentage ("what if the gateway fee was 3%")
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", q)
    if pct_match and field.endswith("_pct"):
        new_value = round(float(pct_match.group(1)) / 100, 6)
        current = getattr(batch, field)
        modified = replace(batch, **{field: new_value})
        label = field.replace("_pct", "").replace("_", " ")
        return modified, f"{label} changed from {current} to {new_value}"

    # Case 3: explicit rupee amount ("what if refunds were 2000")
    amount_match = re.search(r"(?:₹|rs\.?|rupees)?\s*(\d[\d,]*(?:\.\d+)?)", q)
    if amount_match and field.endswith("_amount"):
        raw = amount_match.group(1).replace(",", "")
        new_value = round(float(raw), 2)
        current = getattr(batch, field)
        modified = replace(batch, **{field: new_value})
        label = field.replace("_amount", "").replace("_", " ")
        return modified, f"{label} changed from {current} to {new_value}"

    return None, None


def parse_projection(question: str) -> tuple[Optional[SettlementBatch], Optional[str]]:
    """
    Parse projection questions like "if I make ₹80,000 today, what would I receive?"
    Uses average rates as the baseline and returns a modified batch with the
    projected gross amount.
    
    Returns (projection_batch, description) or (None, None) if not a projection.
    """
    q = clean_question(question).lower()
    
    # Look for projection-style phrasing: "if i" + ("make" or "earn" or "get") + "today"
    projection_keywords = ("if i" in q and ("make" in q or "earn" in q or "get" in q or "receive" in q))
    time_keywords = "today" in q or "tomorrow" in q or "next" in q
    
    if not (projection_keywords and time_keywords):
        return None, None
    
    # Look for a rupee amount
    amount_match = re.search(r"(?:₹|rs\.?|rupees)?\s*(\d[\d,]*(?:\.\d+)?)", q)
    if not amount_match:
        return None, None
    
    raw = amount_match.group(1).replace(",", "")
    projected_gross = round(float(raw), 2)
    
    # Get average batch as template
    avg_batch = _get_average_batch()
    if not avg_batch:
        return None, None
    
    # Calculate projected refunds using average refund ratio
    avg_refund_ratio = (sum(b["refunds_amount"] / b["gross_amount"] for b in db.list_all_batches()) 
                        / len(db.list_all_batches()))
    
    projection = replace(
        avg_batch,
        gross_amount=projected_gross,
        refunds_amount=round(projected_gross * avg_refund_ratio, 2),
    )
    
    return projection, f"Projection at ₹{projected_gross:,.0f} gross (using your recent average rates)"

