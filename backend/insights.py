"""
Settlement Story — insights layer.

Compares one batch against historical averages to flag notable patterns.
This module only ever compares numbers already produced or input values --
it never computes a waterfall or derives new financial figures.
"""

from typing import Optional
import db


def _get_average_rates() -> dict:
    """Calculate average fee rates and refund ratio across all batches."""
    batches = db.list_all_batches()
    if not batches:
        return {}
    
    total_fee_pct = sum(b["gateway_fee_pct"] for b in batches)
    total_reserve_pct = sum(b["chargebacks_reserve_pct"] for b in batches)
    total_refund_ratio = sum(b["refunds_amount"] / b["gross_amount"] for b in batches)
    
    count = len(batches)
    return {
        "avg_gateway_fee_pct": total_fee_pct / count,
        "avg_reserve_pct": total_reserve_pct / count,
        "avg_refund_ratio": total_refund_ratio / count,
    }


def get_batch_insights(batch_id: str) -> Optional[str]:
    """
    Compare a batch against historical averages.
    
    Returns a single plain-text insight if something is notably different,
    or None if the batch is within normal ranges.
    """
    row = db.get_batch_row(batch_id)
    if row is None:
        return None
    
    averages = _get_average_rates()
    if not averages:
        return None
    
    # Compare gateway fee (threshold: 50% higher or lower than average)
    fee_ratio = row["gateway_fee_pct"] / averages["avg_gateway_fee_pct"]
    if fee_ratio > 1.5:
        return f"Your gateway fee this batch is about {fee_ratio:.1f}x your recent average."
    elif fee_ratio < 0.5:
        return f"Your gateway fee this batch is notably lower than recent average (about {1/fee_ratio:.1f}x lower)."
    
    # Compare reserve rate (threshold: 60% higher or lower)
    reserve_ratio = row["chargebacks_reserve_pct"] / averages["avg_reserve_pct"]
    if reserve_ratio > 1.6:
        return f"Your chargeback reserve this batch was about {reserve_ratio:.1f}x your recent average."
    elif reserve_ratio < 0.4 and row["chargebacks_reserve_pct"] > 0:
        return f"Your chargeback reserve this batch is notably lower than recent average."
    
    # Compare refund ratio (threshold: 2x higher or 50% lower)
    current_refund_ratio = row["refunds_amount"] / row["gross_amount"]
    refund_ratio = current_refund_ratio / averages["avg_refund_ratio"]
    if refund_ratio > 2.0:
        return f"Refunds this batch were about {refund_ratio:.1f}x your recent average."
    elif refund_ratio < 0.5 and current_refund_ratio > 0:
        return f"Refunds this batch are notably lower than recent average."
    
    return None
