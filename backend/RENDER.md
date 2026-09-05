# Render Deployment Reference (Backend)

## Dashboard Settings

| Field | Value | Notes |
|---|---|---|
| **Environment** | Python 3 | Python 3.11+ |
| **Root Directory** | ackend | **Crucial**: Must point to ackend |
| **Build Command** | pip install -r requirements.txt | Installs FastAPI, uvicorn, pydantic, pdfplumber, etc. |
| **Start Command** | uvicorn main:app --host 0.0.0.0 --port  | Uses dynamic $PORT injected by Render |
| **Plan** | Free / Starter | Free instances spin down after 15m idle |

## Environment Variables

| Variable | Value | Purpose |
|---|---|---|
| PYTHON_VERSION | 3.11.9 | Sets the Python runtime version |
| NARRATOR_MODE | llm | Uses Gemini 2.5 Flash for conversational explanations (or 	emplate) |
| GEMINI_API_KEY | <your-key> | Required if NARRATOR_MODE=llm |
| CORS_ORIGINS | * | Allows calls from Vercel frontend (can be restricted to Vercel domain) |

## SQLite Ephemeral Storage
Render free tier uses ephemeral container disks:
- On restart or redeploy, settlement_story.db is recreated fresh.
- The 12 reference fixtures are automatically seeded by db.init_db() at startup.
- User-uploaded PDFs do not persist across restarts.
