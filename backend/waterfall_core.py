"""
Settlement Story — core waterfall logic.

THIS FILE IS LOAD-BEARING. Every number the product shows a merchant comes
from compute_waterfall() below. Do not let an LLM regenerate or "improve"
this function -- copy it exactly. If the math here is wrong, the entire
product's credibility is wrong. The LLM narrates WaterfallResult; it never
computes it.
"""

from dataclasses import dataclass


@dataclass
class SettlementBatch:
    id: str
    date: str
    gross_amount: float
    gateway_fee_pct: float          # e.g. 0.02 for 2%
    gst_on_fee_pct: float           # e.g. 0.18 for 18% GST, charged on the fee only
    refunds_amount: float
    chargebacks_reserve_pct: float  # rolling reserve held back, e.g. 0.02


@dataclass
class WaterfallResult:
    gross: float
    gateway_fee: float
    gst_on_fee: float
    refunds: float
    reserve_held: float
    net_settled: float


def compute_waterfall(batch: SettlementBatch) -> WaterfallResult:
    """
    The single source of truth for every number this product shows.
    Deterministic. No external calls, no randomness, no LLM involvement.
    """
    gateway_fee = round(batch.gross_amount * batch.gateway_fee_pct, 2)
    gst_on_fee = round(gateway_fee * batch.gst_on_fee_pct, 2)
    after_fees = round(batch.gross_amount - gateway_fee - gst_on_fee, 2)
    after_refunds = round(after_fees - batch.refunds_amount, 2)
    reserve_held = round(after_refunds * batch.chargebacks_reserve_pct, 2)
    net_settled = round(after_refunds - reserve_held, 2)

    return WaterfallResult(
        gross=batch.gross_amount,
        gateway_fee=gateway_fee,
        gst_on_fee=gst_on_fee,
        refunds=batch.refunds_amount,
        reserve_held=reserve_held,
        net_settled=net_settled,
    )


def assert_waterfall_invariants(result: WaterfallResult) -> None:
    """
    Guardrails against silent drift if this function is ever edited or
    regenerated. Call this after every compute_waterfall() in development
    -- it should never fail. If it does, the function was changed and is
    now wrong.
    """
    assert result.gateway_fee >= 0, "fee cannot be negative"
    assert result.gst_on_fee >= 0, "GST cannot be negative"
    assert result.reserve_held >= 0, "reserve cannot be negative"

    reconstructed = round(
        result.gross - result.gateway_fee - result.gst_on_fee
        - result.refunds - result.reserve_held,
        2,
    )
    assert reconstructed == result.net_settled, (
        f"waterfall does not balance: gross minus every deduction "
        f"({reconstructed}) must exactly equal net_settled ({result.net_settled})"
    )
