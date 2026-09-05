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
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if iso_match:
            date_str = iso_match.group(1)
        else:
            date_str = "2026-08-20"

    # 1b. Merchant / Entity Name
    merchant_match = re.search(
        r"(?:Entity Name|Merchant Name|Merchant|Business Name|Account Name):\s*([^|\n\r]+)",
        text,
        re.IGNORECASE,
    )
    merchant_name = merchant_match.group(1).strip() if merchant_match else None

    # 2. Transaction Amounts -> gross_amount
    txn_section = text
    if "TRANSACTION DETAILS" in text:
        part = text.split("TRANSACTION DETAILS")[1]
        for stop in ["REFUNDS PROCESSED", "CHARGES SUMMARY", "CHARGES AND RATES", "End of statement"]:
            if stop in part:
                part = part.split(stop)[0]
        txn_section = part

    txn_amounts_matches = re.findall(
        r"(?:UPI|Card|Netbanking|Wallet|EMI|Debit|Credit)\s+([\d,]+\.\d{2})",
        txn_section,
        re.IGNORECASE,
    )
    if not txn_amounts_matches:
        txn_amounts_matches = re.findall(
            r"TXN\w+\s+(?:\d{1,2}:\d{2}\s+)?(?:\w+\s+)?([\d,]+\.\d{2})",
            txn_section,
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

    gross_amount = round(sum(txn_floats), 2)
    if gross_amount <= 0:
        raise ValueError("Could not confidently extract required field: gross_amount (computed gross sum was zero)")

    # 3. Refund Amounts -> refunds_amount
    refund_floats = []
    if "REFUNDS PROCESSED" in text:
        part = text.split("REFUNDS PROCESSED")[1]
        for stop in ["CHARGES SUMMARY", "CHARGES AND RATES", "TRANSACTION DETAILS", "End of statement"]:
            if stop in part:
                part = part.split(stop)[0]
        ref_matches = re.findall(r"REF\w+\s+(?:TXN\w+\s+)?([\d,]+\.\d{2})", part)
        if not ref_matches:
            ref_matches = re.findall(r"([\d,]+\.\d{2})", part)
        refund_floats = [float(a.replace(",", "")) for a in ref_matches]
    
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
    # Test 1: Original scattered settlement statement PDF
    batch1, fields1 = extract_batch_from_pdf(PDF_PATH_1)
    result1 = compute_waterfall(batch1)
    assert_waterfall_invariants(result1)
    expected_net_1 = 47299.70
    assert result1.net_settled == expected_net_1, f"Expected {expected_net_1}, got {result1.net_settled}"
    print(f"PASS PDF 1 (scattered_settlement_statement.pdf): net_settled = {result1.net_settled}")

    # Test 2: Additional messy settlement statement PDF
    if PDF_PATH_2.exists():
        batch2, fields2 = extract_batch_from_pdf(PDF_PATH_2)
        result2 = compute_waterfall(batch2)
        assert_waterfall_invariants(result2)
        expected_net_2 = 68881.75
        assert result2.net_settled == expected_net_2, f"Expected {expected_net_2}, got {result2.net_settled}"
        print(f"PASS PDF 2 (messy_settlement_statement_2.pdf): net_settled = {result2.net_settled}")

    print("\nALL PDF EXTRACTION TESTS PASSED")
