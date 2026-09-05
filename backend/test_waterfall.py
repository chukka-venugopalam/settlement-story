import json
import sys
from waterfall_core import SettlementBatch, compute_waterfall, assert_waterfall_invariants

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with open("mock_settlement_data.json") as f:
    fixtures = json.load(f)

all_passed = True

for fixture in fixtures:
    inp = fixture["input"]
    expected = fixture["expected_output"]

    batch = SettlementBatch(
        id=fixture["id"],
        date=fixture["date"],
        gross_amount=inp["gross_amount"],
        gateway_fee_pct=inp["gateway_fee_pct"],
        gst_on_fee_pct=inp["gst_on_fee_pct"],
        refunds_amount=inp["refunds_amount"],
        chargebacks_reserve_pct=inp["chargebacks_reserve_pct"],
    )

    result = compute_waterfall(batch)
    assert_waterfall_invariants(result)

    actual = {
        "gross": result.gross,
        "gateway_fee": result.gateway_fee,
        "gst_on_fee": result.gst_on_fee,
        "refunds": result.refunds,
        "reserve_held": result.reserve_held,
        "net_settled": result.net_settled,
    }

    if actual == expected:
        print(f"PASS  {fixture['id']}: {fixture['label']}")
    else:
        all_passed = False
        print(f"FAIL  {fixture['id']}: {fixture['label']}")
        print(f"  expected: {expected}")
        print(f"  actual:   {actual}")

print()
print("ALL PASSED" if all_passed else "SOME FAILED")
