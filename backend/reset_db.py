"""
One-command pre-pitch database reset and verification script.
Resets settlement_story.db back to the original 12 seeded fixtures,
verifies all fixtures are loaded, and runs waterfall test verification.
"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

db_file = backend_dir / "settlement_story.db"
if db_file.exists():
    try:
        db_file.unlink()
        print(f"[RESET] Removed test database: {db_file.name}")
    except Exception as e:
        print(f"[WARN] Could not delete {db_file.name}: {e}")

import db
db.init_db()

batches = db.list_all_batches()
print(f"[OK] Database re-seeded: {len(batches)} original fixtures loaded.")

# Verify waterfall calculations against all fixtures
import subprocess
print("[VERIFY] Running waterfall invariant tests...")
res = subprocess.run([sys.executable, "test_waterfall.py"], cwd=str(backend_dir))
if res.returncode == 0:
    print("[ALL PASSED] Database is clean and ready for pitch presentation!")
else:
    print(f"[FAIL] Tests failed with exit code {res.returncode}")
    sys.exit(res.returncode)
