"""
Settlement Story — API.

Primary endpoints:

    POST /ask       { question: string, batch_id?: string } -> narrated answer + waterfall breakdown
    GET  /batches    list of synthetic settlement batches, for the demo picker
    GET  /insights/{batch_id}  anomaly flags comparing a batch against historical average
    GET  /           static frontend (index.html)

Every number returned by /ask comes from waterfall_core.compute_waterfall().
The narration layer (narrator.py) only ever formats those numbers into
sentences -- it never derives or alters them. followup.py may swap in
hypothetical *inputs* (e.g. "what if refunds doubled") before the same
locked function runs again, but the function itself is never bypassed.

Insights (insights.py) only compares already-computed numbers or input rates
across historical batches -- it never invents new figures.
"""

from dataclasses import asdict
import email
from email import policy
from pathlib import Path
import os
import sys
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

_extraction_dir = Path(__file__).resolve().parent.parent / "extraction"
if str(_extraction_dir) not in sys.path:
    sys.path.insert(0, str(_extraction_dir))
from extract_from_pdf import extract_batch_from_pdf

import db
from followup import clean_question, parse_followup, parse_projection
from narrator import narrate
from waterfall_core import SettlementBatch, assert_waterfall_invariants, compute_waterfall
from insights import get_batch_insights

# Load environment variables from .env file explicitly
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

logger = logging.getLogger(__name__)

# Module-level configuration read once from environment when the module loads
NARRATOR_MODE = os.getenv("NARRATOR_MODE", "template").lower()
if NARRATOR_MODE not in ("template", "llm"):
    logger.warning(f"Invalid NARRATOR_MODE '{NARRATOR_MODE}', falling back to 'template'")
    NARRATOR_MODE = "template"


app = FastAPI(title="Settlement Story API", version="0.1.0")

# CORS configuration for split deployment:
# Defaults to ["*"] for local dev and demo ease (explicitly permitting requests from Vercel-hosted frontend origins).
# Security tradeoff note: wildcard ("*") allows any origin to query this API.
# For production hardening, set the CORS_ORIGINS environment variable in Render dashboard
# (e.g. CORS_ORIGINS="https://settlement-story.vercel.app,https://your-custom-domain.com").
cors_origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
if cors_origins_raw == "*" or not cors_origins_raw:
    cors_origins = ["*"]
else:
    cors_origins = [orig.strip() for orig in cors_origins_raw.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True if cors_origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # If mode is "llm", require the Gemini API key
    if NARRATOR_MODE == "llm":
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            error_msg = (
                "NARRATOR_MODE is set to 'llm' but GEMINI_API_KEY is missing or empty. "
                "Add your Gemini API key to the .env file or set NARRATOR_MODE='template' to use the default narration. "
                "Get a free key from: https://aistudio.google.com/app/apikeys"
            )
            logger.error(error_msg)
            sys.exit(1)
    
    logger.info(f"Narrator mode: {NARRATOR_MODE}")
    
    # Initialize database
    db.init_db()


class AskRequest(BaseModel):
    question: str
    batch_id: str | None = None


class WaterfallInputs(BaseModel):
    gross_amount: float
    gateway_fee_pct: float
    gst_on_fee_pct: float
    refunds_amount: float
    chargebacks_reserve_pct: float


class WaterfallOut(BaseModel):
    gross: float
    gateway_fee: float
    gst_on_fee: float
    refunds: float
    reserve_held: float
    net_settled: float


class AskResponse(BaseModel):
    question: str
    batch_id: str
    is_hypothetical: bool
    modification_note: str | None
    inputs: WaterfallInputs | None = None
    waterfall: WaterfallOut
    narration: str


class UploadResponse(BaseModel):
    question: str
    batch_id: str
    is_hypothetical: bool
    modification_note: str | None
    inputs: WaterfallInputs
    waterfall: WaterfallOut
    narration: str
    extracted_fields: dict
    document_summary: str | None = None


def _row_to_batch(row: dict) -> SettlementBatch:
    return SettlementBatch(
        id=row["id"],
        date=row["date"],
        gross_amount=row["gross_amount"],
        gateway_fee_pct=row["gateway_fee_pct"],
        gst_on_fee_pct=row["gst_on_fee_pct"],
        refunds_amount=row["refunds_amount"],
        chargebacks_reserve_pct=row["chargebacks_reserve_pct"],
    )


@app.get("/batches")
def get_batches() -> list[dict]:
    return db.list_batches()


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    # Sanitize input: strip quotes and whitespace
    req.question = clean_question(req.question)

    # Try projection first (if no batch_id provided)
    if req.batch_id is None:
        projection, projection_note = parse_projection(req.question)
        if projection:
            result = compute_waterfall(projection)
            assert_waterfall_invariants(result)
            narration = narrate(
                projection,
                result,
                req.question,
                modification_note=projection_note,
                mode=NARRATOR_MODE,
            )
            inputs = WaterfallInputs(
                gross_amount=projection.gross_amount,
                gateway_fee_pct=projection.gateway_fee_pct,
                gst_on_fee_pct=projection.gst_on_fee_pct,
                refunds_amount=projection.refunds_amount,
                chargebacks_reserve_pct=projection.chargebacks_reserve_pct,
            )
            return AskResponse(
                question=req.question,
                batch_id="projection",
                is_hypothetical=True,
                modification_note=projection_note,
                inputs=inputs,
                waterfall=WaterfallOut(**asdict(result)),
                narration=narration,
            )
        else:
            # Question wasn't recognized as a projection -- return helpful guidance
            raise HTTPException(
                status_code=400,
                detail="I can answer questions about a specific settlement, ask live 'what if' scenarios (like \"what if refunds doubled?\"), or handle projection questions (like \"If I make ₹80,000 today, what would I receive?\"). Try rephrasing or pick a settlement above."
            )
    
    # Standard batch-based query
    row = db.get_batch_row(req.batch_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No settlement batch with id '{req.batch_id}'")

    base_batch = _row_to_batch(row)

    # Check whether this is a live "what if" follow-up. If so, run the
    # SAME locked function against adjusted inputs -- the function itself
    # never changes, only what's fed into it.
    modified_batch, modification_note = parse_followup(req.question, base_batch)
    
    # If no modification was recognized, but we have a batch_id, still try to answer the question
    # as a simple explanation of that batch
    if modified_batch is None:
        # Check if this looks like an unclear/unrecognized question
        q_lower = req.question.lower()
        is_clear_lookup = (
            any(word in q_lower for word in ["why", "what", "how", "where", "when", "which", "fee", "refund", "settle", "reserve", "gross", "gst"]) or
            "what if" in q_lower or
            "would happen" in q_lower
        )
        if not is_clear_lookup and len(req.question.strip()) > 0:
            # Unclear question, but we have a batch -- return guidance
            raise HTTPException(
                status_code=400,
                detail="Could you clarify your question? Try: 'Why was my settlement lower?', 'What was the gateway fee?', or 'What if my refunds doubled?'"
            )
    
    batch_to_compute = modified_batch if modified_batch is not None else base_batch
    is_hypothetical = modified_batch is not None

    result = compute_waterfall(batch_to_compute)
    assert_waterfall_invariants(result)  # never trust silently -- always re-check

    narration = narrate(
        batch_to_compute,
        result,
        req.question,
        modification_note=modification_note,
        mode=NARRATOR_MODE,
    )

    inputs = WaterfallInputs(
        gross_amount=batch_to_compute.gross_amount,
        gateway_fee_pct=batch_to_compute.gateway_fee_pct,
        gst_on_fee_pct=batch_to_compute.gst_on_fee_pct,
        refunds_amount=batch_to_compute.refunds_amount,
        chargebacks_reserve_pct=batch_to_compute.chargebacks_reserve_pct,
    )

    return AskResponse(
        question=req.question,
        batch_id=req.batch_id,
        is_hypothetical=is_hypothetical,
        modification_note=modification_note,
        inputs=inputs,
        waterfall=WaterfallOut(**asdict(result)),
        narration=narration,
    )


def _parse_multipart_pdf(content_type: str, body: bytes) -> tuple[str, bytes]:
    """Parse raw bytes or multipart form data to extract the uploaded PDF bytes and filename."""
    if not body or len(body) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty (0 bytes). Please upload a valid settlement statement PDF.")

    if "multipart/form-data" in content_type:
        msg = email.message_from_bytes(
            f"Content-Type: {content_type}\r\n\r\n".encode("latin-1") + body,
            policy=policy.default,
        )
        for part in msg.iter_parts():
            fn = part.get_filename() or "statement.pdf"
            payload = part.get_payload(decode=True)
            if payload is not None:
                if len(payload) == 0:
                    raise HTTPException(status_code=400, detail=f"The uploaded file '{fn}' is empty (0 bytes). Please upload a valid settlement statement PDF.")
                return fn, payload
        raise HTTPException(status_code=400, detail="No file payload found in the multipart form upload.")
    elif "pdf" in content_type.lower() or body.startswith(b"%PDF"):
        if len(body) == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty (0 bytes). Please upload a valid settlement statement PDF.")
        return "statement.pdf", body
    else:
        idx = body.find(b"%PDF")
        if idx != -1:
            return "statement.pdf", body[idx:]
        raise HTTPException(status_code=400, detail="Unsupported upload format. Please upload a valid .pdf file.")


@app.post("/upload", response_model=UploadResponse)
async def upload(request: Request) -> UploadResponse:
    """Accept multipart/form-data PDF statement uploads, extract fields, and compute the waterfall."""
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    if not body or len(body) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty (0 bytes). Please upload a valid settlement statement PDF.")

    filename, pdf_bytes = _parse_multipart_pdf(content_type, body)

    if not pdf_bytes or len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail=f"The uploaded file '{filename}' is empty (0 bytes). Please upload a valid settlement statement PDF.")

    # Validate PDF magic header
    if b"%PDF" not in pdf_bytes[:1024]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format for '{filename}': File does not contain a valid PDF header (%PDF). Please upload a genuine PDF settlement statement."
        )

    try:
        batch, extracted_fields = extract_batch_from_pdf(pdf_bytes, batch_id=f"pdf-{filename}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Unexpected error extracting PDF: {e}")
        raise HTTPException(status_code=422, detail=f"Failed to process settlement statement '{filename}': {str(e)}")

    # Persist the extracted batch so subsequent questions and follow-ups can query it
    try:
        db.save_batch(batch, label=f"Uploaded: {filename}")
    except Exception as e:
        logger.warning(f"Failed to persist uploaded batch to database: {e}")

    # Feed extracted batch through the LOCKED compute_waterfall function
    try:
        result = compute_waterfall(batch)
        assert_waterfall_invariants(result)
    except Exception as e:
        logger.exception(f"Calculation error on extracted batch: {e}")
        raise HTTPException(status_code=422, detail=f"Settlement invariant failure: {str(e)}")

    try:
        narration = narrate(
            batch,
            result,
            question=f"Statement extracted from {filename}",
            modification_note=None,
            mode=NARRATOR_MODE,
        )
    except Exception as e:
        logger.warning(f"Narration failed during upload ({e}), falling back to template narration")
        from narrator import narrate_template
        narration = narrate_template(batch, result, question=f"Statement extracted from {filename}")

    inputs = WaterfallInputs(
        gross_amount=batch.gross_amount,
        gateway_fee_pct=batch.gateway_fee_pct,
        gst_on_fee_pct=batch.gst_on_fee_pct,
        refunds_amount=batch.refunds_amount,
        chargebacks_reserve_pct=batch.chargebacks_reserve_pct,
    )

    return UploadResponse(
        question=f"Uploaded Statement: {filename}",
        batch_id=batch.id,
        is_hypothetical=False,
        modification_note=None,
        inputs=inputs,
        waterfall=WaterfallOut(**asdict(result)),
        narration=narration,
        extracted_fields=extracted_fields,
        document_summary=extracted_fields.get("document_summary"),
    )


@app.get("/insights/{batch_id}")
def get_insights(batch_id: str) -> dict:
    """Anomaly detection: compare batch against historical average."""
    insight = get_batch_insights(batch_id)
    return {"batch_id": batch_id, "insight": insight}


@app.get("/compare")
def compare(batch_id_a: str, batch_id_b: str) -> dict:
    """Compare two settlements side by side.
    
    Returns both waterfalls plus a plain-English line on the biggest driver
    of the difference between them.
    """
    row_a = db.get_batch_row(batch_id_a)
    row_b = db.get_batch_row(batch_id_b)
    
    if row_a is None:
        raise HTTPException(status_code=404, detail=f"No settlement batch with id '{batch_id_a}'")
    if row_b is None:
        raise HTTPException(status_code=404, detail=f"No settlement batch with id '{batch_id_b}'")
    
    batch_a = _row_to_batch(row_a)
    batch_b = _row_to_batch(row_b)
    
    result_a = compute_waterfall(batch_a)
    result_b = compute_waterfall(batch_b)
    
    assert_waterfall_invariants(result_a)
    assert_waterfall_invariants(result_b)
    
    # Find the biggest difference between the two results
    deductions_a = {
        "gateway_fee": result_a.gateway_fee,
        "gst_on_fee": result_a.gst_on_fee,
        "refunds": result_a.refunds,
        "reserve_held": result_a.reserve_held,
    }
    deductions_b = {
        "gateway_fee": result_b.gateway_fee,
        "gst_on_fee": result_b.gst_on_fee,
        "refunds": result_b.refunds,
        "reserve_held": result_b.reserve_held,
    }
    
    # Calculate the absolute difference for each line item
    differences = {}
    for key in deductions_a:
        diff = abs(deductions_a[key] - deductions_b[key])
        differences[key] = diff
    
    # Find the largest difference
    biggest_diff_key = max(differences, key=differences.get)
    biggest_diff_value = differences[biggest_diff_key]
    
    # Build a narrative line about the biggest driver
    key_label = biggest_diff_key.replace("_", " ").title()
    amt_a = deductions_a[biggest_diff_key]
    amt_b = deductions_b[biggest_diff_key]

    if amt_a > amt_b:
        comparison_note = f"The biggest difference: {key_label} was ₹{amt_a:.2f} in {batch_id_a} vs ₹{amt_b:.2f} in {batch_id_b} — that's a ₹{biggest_diff_value:.2f} swing."
    else:
        comparison_note = f"The biggest difference: {key_label} was ₹{amt_b:.2f} in {batch_id_b} vs ₹{amt_a:.2f} in {batch_id_a} — that's a ₹{biggest_diff_value:.2f} swing."

    inputs_a = WaterfallInputs(
        gross_amount=batch_a.gross_amount,
        gateway_fee_pct=batch_a.gateway_fee_pct,
        gst_on_fee_pct=batch_a.gst_on_fee_pct,
        refunds_amount=batch_a.refunds_amount,
        chargebacks_reserve_pct=batch_a.chargebacks_reserve_pct,
    )
    inputs_b = WaterfallInputs(
        gross_amount=batch_b.gross_amount,
        gateway_fee_pct=batch_b.gateway_fee_pct,
        gst_on_fee_pct=batch_b.gst_on_fee_pct,
        refunds_amount=batch_b.refunds_amount,
        chargebacks_reserve_pct=batch_b.chargebacks_reserve_pct,
    )

    return {
        "batch_a": {"id": batch_id_a, "inputs": inputs_a, "waterfall": WaterfallOut(**asdict(result_a))},
        "batch_b": {"id": batch_id_b, "inputs": inputs_b, "waterfall": WaterfallOut(**asdict(result_b))},
        "comparison_note": comparison_note,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ========== STATIC FILE MOUNTS ==========
# All API routes MUST be registered before StaticFiles mounts,
# since StaticFiles with html=True will serve any unmatched path.

frontend_dir = Path(__file__).parent.parent / "frontend"
landing_dir = Path(__file__).parent.parent / "landing"
fonts_dir = frontend_dir / "fonts"

# Serve landing page at root (marketing/explainer page)
@app.get("/")
async def root():
    """Serve landing/index.html at the root path, or API info if static assets not present."""
    index_file = landing_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return {"status": "ok", "service": "Settlement Story API", "docs": "/docs"}

# Serve landing page also at /landing
@app.get("/landing")
async def landing():
    """Serve landing/index.html at /landing."""
    index_file = landing_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return {"status": "ok", "service": "Settlement Story API", "docs": "/docs"}

# Serve actual app at /app
@app.get("/app")
async def app_route():
    """Serve frontend/index.html at /app."""
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return {"status": "ok", "service": "Settlement Story API", "docs": "/docs"}

# Mount fonts directory at /fonts
if fonts_dir.exists():
    app.mount("/fonts", StaticFiles(directory=fonts_dir), name="fonts")

# Mount landing static files under /landing/static
if landing_dir.exists():
    app.mount("/landing/static", StaticFiles(directory=landing_dir), name="landing-static")

# Mount frontend static files (CSS, fonts, etc.) under /static
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

