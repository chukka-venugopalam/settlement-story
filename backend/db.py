"""
Settlement Story — data layer.

Seeds a SQLite table from mock_settlement_data.json (the same fixtures
already proven against waterfall_core.py in test_waterfall.py) and exposes
simple lookups.
Nothing here computes a waterfall -- this module only stores and retrieves
the raw SettlementBatch inputs.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "settlement_story.db"
SEED_PATH = Path(__file__).parent / "mock_settlement_data.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settlement_batches (
    id                       TEXT PRIMARY KEY,
    label                    TEXT NOT NULL,
    date                     TEXT NOT NULL,
    gross_amount             REAL NOT NULL,
    gateway_fee_pct          REAL NOT NULL,
    gst_on_fee_pct           REAL NOT NULL,
    refunds_amount           REAL NOT NULL,
    chargebacks_reserve_pct  REAL NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(reseed: bool = False) -> None:
    """Create the table if missing, and seed it from mock_settlement_data.json
    if empty (or unconditionally if reseed=True). Safe to call on every app
    startup."""
    conn = get_connection()
    try:
        conn.execute(SCHEMA)
        conn.commit()

        if reseed:
            conn.execute("DELETE FROM settlement_batches")
            conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM settlement_batches").fetchone()[0]
        if count == 0:
            with open(SEED_PATH) as f:
                fixtures = json.load(f)
            for fixture in fixtures:
                inp = fixture["input"]
                conn.execute(
                    """INSERT INTO settlement_batches
                       (id, label, date, gross_amount, gateway_fee_pct,
                        gst_on_fee_pct, refunds_amount, chargebacks_reserve_pct)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fixture["id"],
                        fixture["label"],
                        fixture["date"],
                        inp["gross_amount"],
                        inp["gateway_fee_pct"],
                        inp["gst_on_fee_pct"],
                        inp["refunds_amount"],
                        inp["chargebacks_reserve_pct"],
                    ),
                )
            conn.commit()
    finally:
        conn.close()


def list_batches() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, label, date, gross_amount FROM settlement_batches ORDER BY date"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_all_batches() -> list[dict]:
    """Return all batch rows with all columns, for averaging/comparison."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM settlement_batches ORDER BY date"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_batch_row(batch_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM settlement_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_batch(batch, label: str = "Uploaded PDF") -> None:
    """Save or update a settlement batch in the database."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO settlement_batches
               (id, label, date, gross_amount, gateway_fee_pct,
                gst_on_fee_pct, refunds_amount, chargebacks_reserve_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                batch.id,
                label,
                batch.date,
                batch.gross_amount,
                batch.gateway_fee_pct,
                batch.gst_on_fee_pct,
                batch.refunds_amount,
                batch.chargebacks_reserve_pct,
            ),
        )
        conn.commit()
    finally:
        conn.close()

