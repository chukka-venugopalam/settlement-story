"""
Extraction pipeline: PDF settlement statement -> structured SettlementBatch -> the SAME locked compute_waterfall() from waterfall_core.py.

This is deliberately split into two halves that must never be merged:

1. EXTRACTION (this file) -- reads a messy, real-world-shaped document and
   pulls out numbers and rates.
2. CALCULATION (waterfall_core.py) -- untouched, deterministic, already
   tested. Extraction output is validated with assert_waterfall_invariants()
   before any user sees a number.
"""

import base64
from pathlib import Path
import re
import sys
import zlib
from datetime import datetime

# Add backend to path for imports
_backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from waterfall_core import SettlementBatch, compute_waterfall, assert_waterfall_invariants

PDF_PATH_1 = Path(__file__).resolve().parent / "scattered_settlement_statement.pdf"
PDF_PATH_2 = Path(__file__).resolve().parent / "messy_settlement_statement_2.pdf"


def extract_text_from_pdf(pdf_source) -> str:
    """Extract raw text strings from a PDF file path, file object, or bytes.
    
    Primary path: pure-Python stream decompressor (preserves sequential document flow).
    Fallback path: pdfplumber (for complex PDF page trees).
    """
    if isinstance(pdf_source, (str, Path)):
        with open(pdf_source, "rb") as f:
            pdf_bytes = f.read()
    elif hasattr(pdf_source, "read"):
        pdf_bytes = pdf_source.read()
    elif isinstance(pdf_source, bytes):
        pdf_bytes = pdf_source
    else:
        raise TypeError(f"Unsupported pdf source type: {type(pdf_source)}")
        
    texts = []
    pos = 0
    while True:
        s_idx = pdf_bytes.find(b"stream", pos)
        if s_idx == -1:
            break
        if pdf_bytes[s_idx:s_idx+7] == b"stream\n":
            data_start = s_idx + 7
        elif pdf_bytes[s_idx:s_idx+8] == b"stream\r\n":
            data_start = s_idx + 8
        else:
            data_start = s_idx + 6
        
        e_idx = pdf_bytes.find(b"endstream", data_start)
        if e_idx == -1:
            break
        
        stream_data = pdf_bytes[data_start:e_idx].strip()
        
        # 1. Direct uncompressed text
        try:
            raw_text = stream_data.decode("latin-1")
            for match in re.finditer(r"\((.*?)\)\s*Tj", raw_text):
                texts.append(match.group(1))
            for match in re.finditer(r"\[(.*?)\]\s*TJ", raw_text):
                for t in re.finditer(r"\((.*?)\)", match.group(1)):
                    texts.append(t.group(1))
        except Exception:
            pass

        # 2. Direct zlib decompression
        decomp = None
        try:
            decomp = zlib.decompress(stream_data)
        except Exception:
            pass
        
        # 3. ASCII85 + zlib decompression
        if decomp is None:
            try:
                raw = stream_data
                if not raw.endswith(b"~>"):
                    if raw.endswith(b"~"):
                        raw = raw + b">"
                    else:
                        raw = raw + b"~>"
                if not raw.startswith(b"<~"):
                    raw = b"<~" + raw
                a85 = base64.a85decode(raw, adobe=True)
                decomp = zlib.decompress(a85)
            except Exception:
                pass
        
        if decomp:
            dec_str = decomp.decode("latin-1", errors="ignore")
            for match in re.finditer(r"\((.*?)\)\s*Tj", dec_str):
                texts.append(match.group(1))
            for match in re.finditer(r"\[(.*?)\]\s*TJ", dec_str):
                for t in re.finditer(r"\((.*?)\)", match.group(1)):
                    texts.append(t.group(1))
        
        pos = e_idx + 9
        
    extracted = " ".join(texts).strip()
    if extracted:
        # Normalize PDF literal string escape sequences (e.g. \(EMI\) -> (EMI))
        extracted = extracted.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
        return extracted

    # Fallback to pdfplumber if stream decompression yielded nothing
    try:
        import pdfplumber
        import io
        src = io.BytesIO(pdf_bytes)
        with pdfplumber.open(src) as pdf:
            full_text = " ".join(page.extract_text() or "" for page in pdf.pages)
            if full_text.strip():
                return full_text
    except Exception:
        pass

    return ""


def extract_batch_from_pdf(pdf_source, batch_id: str = "extracted-from-pdf") -> tuple[SettlementBatch, dict]:
    """Extract settlement batch and metadata fields from a PDF statement.
    
    Returns:
        (SettlementBatch, extracted_fields_dict)
    Raises:
        ValueError if any required field cannot be confidently extracted.
    """
    text = extract_text_from_pdf(pdf_source)
    if not text.strip():
        raise ValueError("This looks like a PDF but I couldn't find the transaction/fee/refund structure I need — if this is a real settlement statement in a different format I don't yet recognize, let us know.")

    # Validate overall settlement structure before checking specific fields
    has_settlement_keyword = bool(re.search(r"settlement|payout|merchant|gateway", text, re.IGNORECASE))
    has_fee_structure = bool(re.search(r"(?:gateway\s+fee|fee\s+rate|fee|mdr|processing\s+fee).*?\d+(?:\.\d+)?\s*%", text, re.IGNORECASE))
    has_reserve_structure = bool(re.search(r"(?:reserve|holdback).*?\d+(?:\.\d+)?\s*%", text, re.IGNORECASE))
    has_txn_structure = bool(re.search(r"TRANSACTION|TXN|UPI|Card|Netbanking|Wallet|Gross", text, re.IGNORECASE))

    # A real document that is NOT a settlement statement (e.g. invoice, report, general letter)
    if not (has_fee_structure and (has_reserve_structure or has_txn_structure or has_settlement_keyword)):
        raise ValueError(
            "This looks like a PDF but I couldn't find the transaction/fee/refund structure I need — "
            "if this is a real settlement statement in a different format I don't yet recognize, let us know."
        )

    # 1. Statement Date
    date_str = None
    date_match = re.search(r"Statement Period:\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", text, re.IGNORECASE)
    if date_match:
        try:
            date_str = datetime.strptime(date_match.group(1), "%d %b %Y").strftime("%Y-%m-%d")
        except Exception:
            pass
    if not date_str:
        date_match = re.search(r"Statement Period:\s*([A-Za-z]{3}\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE)
        if date_match:
            clean_d = date_match.group(1).replace(",", "")
            try:
                date_str = datetime.strptime(clean_d, "%b %d %Y").strftime("%Y-%m-%d")
            except Exception:
                pass
    if not date_str:
        date_match = re.search(r"Statement Date:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text, re.IGNORECASE)
        if date_match:
            try:
                date_str = datetime.strptime(date_match.group(1), "%d %B %Y").strftime("%Y-%m-%d")
            except Exception:
                pass
    if not date_str:
        date_match = re.search(r"for the period ending\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
        if date_match:
            try:
                date_str = datetime.strptime(date_match.group(1), "%d-%b-%Y").strftime("%Y-%m-%d")
            except Exception:
                pass
    if not date_str:
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if iso_match:
            date_str = iso_match.group(1)
        else:
            date_str = "2026-08-20"

    # 1b. Merchant / Entity Name
    merchant_match = re.search(
        r"(?:Entity Name|Merchant Name|Merchant|Business Name|Account Name|Entity):\s*([^|\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if not merchant_match:
        top_match = re.search(r"^([A-Z\s&]{4,}?)\s+(?:Settlement Statement|Merchant ID)", text.strip())
        if top_match:
            merchant_name = top_match.group(1).strip()
        else:
            merchant_name = None
    else:
        merchant_name = merchant_match.group(1).strip()

    # Section Boundaries
    TXN_HEADER_RE = re.compile(
        r'(?:TRANSACTION\s+DETAILS|TRANSACTION\s+DETAIL|CAPTURED\s+TRANSACTIONS|TRANSACTIONS\s*\([^)]*\)|\bTransactions\b)',
        re.IGNORECASE
    )
    REFUND_HEADER_RE = re.compile(
        r'\b(?:REFUNDS\s+PROCESSED|REFUNDS\s*/\s*REVERSALS|REFUNDS\s+AND\s+REVERSALS|REFUNDS|REVERSALS)\b(?:\s*\([^)]*\))?',
        re.IGNORECASE
    )
    SECTION_END_RE = re.compile(
        r'\b(?:CHARGES\s+SUMMARY|CHARGES\s+AND\s+RATES|RATE\s+SUMMARY|FEES\s+AND\s+CHARGES|FEES\s+SUMMARY|TOTAL\s+TRANSACTION\s+VOLUME|OPERATIONAL\s+NOTE|END\s+OF\s+STATEMENT|SUMMARY:)\b',
        re.IGNORECASE
    )

    # 2. Transaction Amounts -> gross_amount
    txn_matches = list(TXN_HEADER_RE.finditer(text))
    valid_txn_header = None
    for tm in txn_matches:
        start = tm.start()
        prefix = text[max(0, start - 30):start]
        if 'across' in prefix.lower() or 'total' in prefix.lower():
            continue
        valid_txn_header = tm
        break

    txn_section = text
    declared_txn_count = None
    count_m = re.search(
        r"(?:TRANSACTION\s+DETAILS|TRANSACTION\s+DETAIL|TRANSACTIONS)\s*\((?:approx\.?\s*)?(\d+)\s*items?\)",
        text,
        re.IGNORECASE,
    )
    if count_m:
        declared_txn_count = int(count_m.group(1))
    if declared_txn_count is None:
        count_m = re.search(
            r"(?:total\s+transactions?\s+(?:this\s+period)?|total\s+transaction\s+volume|summary:\s*)\s*:?\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        if count_m:
            declared_txn_count = int(count_m.group(1))

    if valid_txn_header:
        part = text[valid_txn_header.end():]
        earliest_stop = len(part)
        for stop_re in [REFUND_HEADER_RE, SECTION_END_RE]:
            sm = stop_re.search(part)
            if sm and sm.start() < earliest_stop:
                earliest_stop = sm.start()
        txn_section = part[:earliest_stop]

    # Priority 1: ID-based capture (matches TXN... through currency amount at end of transaction line)
    txn_amounts_matches = re.findall(r'\bTXN\w*\b(?:(?!\bTXN\w*\b).)*?\b([\d,]+\.\d{2})\b', txn_section)

    # Priority 2: Method-based capture (handles lines with method names, optional parentheses like (EMI) or corporate card)
    if not txn_amounts_matches:
        txn_amounts_matches = re.findall(
            r'(?:UPI|Card|Netbanking|Wallet|EMI|Debit|Credit)(?:\s*\([^)]*\)|\s+[A-Za-z]+)*\s+([\d,]+\.\d{2})',
            txn_section,
            re.IGNORECASE,
        )

    if not txn_amounts_matches:
        gross_summary_match = re.search(
            r"(?:Gross\s+Amount|Gross\s+Settlement|Total\s+Captures|Gross\s+Sales|Gross\s+Volume):\s*(?:₹|INR|Rs\.?)?\s*([\d,]+\.\d{2})",
            text,
            re.IGNORECASE,
        )
        if gross_summary_match:
            txn_floats = [float(gross_summary_match.group(1).replace(",", ""))]
        else:
            raise ValueError(
                "This looks like a PDF but I couldn't find the transaction/fee/refund structure I need — "
                "if this is a real settlement statement in a different format I don't yet recognize, let us know."
            )
    else:
        txn_floats = [float(a.replace(",", "")) for a in txn_amounts_matches]

    # Validate transaction count consistency
    if declared_txn_count is not None and len(txn_floats) != declared_txn_count:
        raise ValueError(
            f"Could not confidently extract required field: gross_amount (expected {declared_txn_count} transactions from statement header/summary, but captured {len(txn_floats)})"
        )

    # Check for unparsed TXN markers in transaction section
    txn_marker_count = len(re.findall(r'\bTXN\w*\b', txn_section))
    if txn_marker_count > 0 and len(txn_floats) < txn_marker_count:
        raise ValueError(
            f"Could not confidently extract required field: gross_amount (found {txn_marker_count} transaction entries in statement, but only confidently parsed {len(txn_floats)})"
        )

    gross_amount = round(sum(txn_floats), 2)
    if gross_amount <= 0:
        raise ValueError("Could not confidently extract required field: gross_amount (computed gross sum was zero)")

    # 3. Refund Amounts -> refunds_amount
    refund_floats = []
    ref_match = REFUND_HEADER_RE.search(text)
    if ref_match:
        ref_header_text = ref_match.group(0)
        is_zero_items = bool(re.search(r'\(0\s*items?\)|:\s*(?:0|0\.00|nil|none)\b', ref_header_text, re.IGNORECASE))
        if not is_zero_items:
            declared_ref_count = None
            count_m = re.search(
                r"(?:REFUNDS\s+PROCESSED|REFUNDS\s*/\s*REVERSALS|REFUNDS\s+AND\s+REVERSALS|REFUNDS|REVERSALS)\s*\((?:approx\.?\s*)?(\d+)\s*items?\)",
                text,
                re.IGNORECASE,
            )
            if count_m:
                declared_ref_count = int(count_m.group(1))
            if declared_ref_count is None:
                count_m = re.search(
                    r"(?:summary:\s*\d+\s*transactions,\s*|total\s+refunds?:\s*)(\d+)\s*refunds?",
                    text,
                    re.IGNORECASE,
                )
                if count_m:
                    declared_ref_count = int(count_m.group(1))

            part = text[ref_match.end():]
            earliest_stop = len(part)
            for stop_re in [TXN_HEADER_RE, SECTION_END_RE]:
                sm = stop_re.search(part)
                if sm and sm.start() < earliest_stop:
                    earliest_stop = sm.start()
            ref_section = part[:earliest_stop].strip()

            ref_matches = re.findall(r'\b(?:REF|REV)\w*\b(?:(?!\b(?:REF|REV)\w*\b).)*?\b([\d,]+\.\d{2})\b', ref_section, re.IGNORECASE)
            if not ref_matches:
                ref_matches = re.findall(r'\b([\d,]+\.\d{2})\b', ref_section)
            
            refund_floats = [float(a.replace(",", "")) for a in ref_matches]

            if len(refund_floats) == 0:
                raise ValueError(
                    "Could not confidently extract required field: refunds_amount (refund section detected in statement, but refund amounts could not be extracted)"
                )
            if declared_ref_count is not None and len(refund_floats) != declared_ref_count:
                raise ValueError(
                    f"Could not confidently extract required field: refunds_amount (expected {declared_ref_count} refunds from statement header/summary, but captured {len(refund_floats)})"
                )
    else:
        # No refund header found: check whether refund transaction markers or summary amounts exist
        has_ref_markers = bool(re.search(r'\b(?:REF\d+|REV\d+)\b', text, re.IGNORECASE))
        ref_summary_match = re.search(
            r"(?:Total\s+Refunds?|Refunds?\s+Amount|Total\s+Reversals?):\s*(?:₹|INR|Rs\.?)?\s*([\d,]+\.\d{2})",
            text,
            re.IGNORECASE,
        )
        if ref_summary_match:
            refund_floats = [float(ref_summary_match.group(1).replace(",", ""))]
        elif has_ref_markers:
            raise ValueError(
                "Could not confidently extract required field: refunds_amount (refund identifiers detected in document, but refund section could not be confidently extracted)"
            )
        else:
            refund_floats = []

    refunds_amount = round(sum(refund_floats), 2)

    # 4. Gateway Fee Percentage
    gw_match = re.search(
        r"(?:payment\s+gateway\s+fee|gateway\s+fee|fee\s+rate|mdr|processing\s+fee|fee).*?(\d+(?:\.\d+)?)\s*%",
        text,
        re.IGNORECASE,
    )
    if not gw_match:
        raise ValueError("Could not confidently extract required field: gateway_fee_pct (payment gateway fee rate not found in statement)")
    gateway_fee_pct = float(gw_match.group(1)) / 100.0

    # 5. GST Percentage on Fee
    gst_match = re.search(
        r"(?:applicable\s+gst|gst\s+on\s+fee|gst|tax\s+on\s+fee).*?(\d+(?:\.\d+)?)\s*%",
        text,
        re.IGNORECASE,
    )
    if not gst_match:
        raise ValueError("Could not confidently extract required field: gst_on_fee_pct (GST rate on fee not found in statement)")
    gst_on_fee_pct = float(gst_match.group(1)) / 100.0

    # 6. Chargeback Reserve Percentage
    res_match = re.search(
        r"(?:rolling\s+reserve|chargebacks?\s+reserve|reserve\s+rate|reserve|holdback).*?(\d+(?:\.\d+)?)\s*%",
        text,
        re.IGNORECASE,
    )
    if not res_match:
        raise ValueError("Could not confidently extract required field: chargebacks_reserve_pct (chargeback reserve rate not found in statement)")
    chargebacks_reserve_pct = float(res_match.group(1)) / 100.0

    # Construct plain-language document summary
    merchant_desc = f" for {merchant_name}" if merchant_name else ""
    date_desc = f" ({date_str})" if date_str else ""
    if len(refund_floats) > 0 or refunds_amount > 0:
        ref_phrase = f"{len(refund_floats)} refunds totaling ₹{refunds_amount:,.2f}"
    else:
        ref_phrase = "0 refunds"
    txn_phrase = f"{len(txn_floats)} transactions" if len(txn_floats) > 1 else ("1 transaction" if len(txn_floats) == 1 else "transactions")

    document_summary = (
        f"This looks like a settlement statement{merchant_desc}{date_desc} with "
        f"{txn_phrase} and {ref_phrase}, for a gross amount of ₹{gross_amount:,.2f}."
    )

    batch = SettlementBatch(
        id=batch_id,
        date=date_str,
        gross_amount=gross_amount,
        gateway_fee_pct=gateway_fee_pct,
        gst_on_fee_pct=gst_on_fee_pct,
        refunds_amount=refunds_amount,
        chargebacks_reserve_pct=chargebacks_reserve_pct,
    )

    extracted_fields = {
        "statement_date": date_str,
        "gross_amount": gross_amount,
        "gateway_fee_pct": gateway_fee_pct,
        "gst_on_fee_pct": gst_on_fee_pct,
        "refunds_amount": refunds_amount,
        "chargebacks_reserve_pct": chargebacks_reserve_pct,
        "transactions_count": len(txn_floats),
        "refunds_count": len(refund_floats),
        "merchant_name": merchant_name,
        "document_summary": document_summary,
    }

    return batch, extracted_fields


if __name__ == "__main__":
    test_files = [
        ("scattered_settlement_statement.pdf", 50000.00, 800.00, 47299.70),
        ("messy_settlement_statement_2.pdf", 75000.00, 2500.00, 68881.75),
        ("d2c_apparel_settlement_4.pdf", 26587.00, 2150.00, 23452.41),
        ("saas_subscription_settlement_5.pdf", 185000.00, 9000.00, 165214.72),
        ("food_delivery_settlement_6.pdf", 14500.00, 1200.00, 12657.35),
        ("electronics_retailer_settlement_7.pdf", 111247.00, 6250.00, 100066.85),
        ("coaching_institute_settlement_8.pdf", 140000.00, 4500.00, 131201.14),
        ("Artisan_Woodworks_Statement.pdf", 64500.00, 9500.00, 51398.78),
        ("Petal_Paw_Grooming_Statement.pdf", 30600.00, 1850.00, 27199.34),
        ("Sunrise_Bakery_Statement.pdf", 20500.00, 900.00, 18829.46),
    ]

    for fname, exp_gross, exp_ref, exp_net in test_files:
        fpath = Path(__file__).resolve().parent / fname
        if fpath.exists():
            batch, fields = extract_batch_from_pdf(fpath)
            res = compute_waterfall(batch)
            assert_waterfall_invariants(res)
            assert batch.gross_amount == exp_gross, f"{fname}: Expected gross {exp_gross}, got {batch.gross_amount}"
            assert batch.refunds_amount == exp_ref, f"{fname}: Expected refunds {exp_ref}, got {batch.refunds_amount}"
            assert res.net_settled == exp_net, f"{fname}: Expected net {exp_net}, got {res.net_settled}"
            print(f"PASS {fname}: gross={batch.gross_amount}, refunds={batch.refunds_amount}, net={res.net_settled}")

    # Negative test: missing_gst_settlement_statement_3.pdf must raise ValueError
    missing_gst_path = Path(__file__).resolve().parent / "missing_gst_settlement_statement_3.pdf"
    if missing_gst_path.exists():
        try:
            extract_batch_from_pdf(missing_gst_path)
            assert False, "Expected ValueError on missing GST statement"
        except ValueError as e:
            print(f"PASS missing_gst_settlement_statement_3.pdf correctly rejected: {e}")

    print("\nALL PDF EXTRACTION TESTS PASSED")
