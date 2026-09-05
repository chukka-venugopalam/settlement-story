# Split Deployment Guide: Render (Backend) + Vercel (Frontend)

This guide details how to deploy **Settlement Story** using a split-architecture setup from the same GitHub repository:
- **Backend API**: Python FastAPI on **Render**
- **Frontend & Landing**: Static HTML + assets on **Vercel**
- **Local Dev**: Unified server via ./run.sh remains 100% unchanged.

---

## 1. Architecture Overview

| Component | Host | Path in Repo | URL Routing |
|---|---|---|---|
| **Backend API** | Render Web Service | ackend/ | https://<render-service>.onrender.com |
| **Landing Page** | Vercel | landing/index.html | https://<vercel-project>.vercel.app/ |
| **App UI** | Vercel | rontend/index.html | https://<vercel-project>.vercel.app/app |
| **Fonts & Assets**| Vercel | rontend/fonts/ | https://<vercel-project>.vercel.app/fonts/* |

---

## 2. Backend Deployment on Render

### Option A: Automatic via Blueprint (ender.yaml)
A ender.yaml blueprint is pre-configured at the repository root. When creating a new Blueprint in Render, connect your GitHub repository and it will automatically apply:
- Service Name: settlement-story-api
- Root Directory: ackend
- Build Command: pip install -r requirements.txt
- Start Command: uvicorn main:app --host 0.0.0.0 --port 

### Option B: Manual Web Service Setup via Dashboard
1. Go to **[Render Dashboard](https://dashboard.render.com/)** -> **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure the following fields:
   - **Name**: settlement-story-api (or your choice)
   - **Language**: Python 3
   - **Branch**: main
   - **Root Directory**: ackend *(CRITICAL: must be set to ackend)*
   - **Build Command**: pip install -r requirements.txt
   - **Start Command**: uvicorn main:app --host 0.0.0.0 --port 
4. In the **Environment Variables** section, add:
   - PYTHON_VERSION: 3.11.9
   - NARRATOR_MODE: llm (or 	emplate to run offline without external API keys)
   - GEMINI_API_KEY: AIzaSy... (Get from [Google AI Studio](https://aistudio.google.com/app/apikeys))
   - CORS_ORIGINS: * *(Allows requests from Vercel; can be tightened to https://<your-project>.vercel.app)*

> [!WARNING]
> ### SQLite Ephemeral Disk on Render Free Tier
> Render's free tier uses an **ephemeral disk**. When the web service spins down due to inactivity (after 15 minutes of no requests) or when a new deployment is triggered:
> - The database file settlement_story.db is reset.
> - db.init_db() automatically runs on container startup and re-seeds all **12 verified reference fixtures**.
> - Any PDF files uploaded via /upload during a previous session will **not** persist across container restarts.
> 
> **Pitch Tip**: Free tier services experience a cold start (~30-50s). Ping https://<render-service>.onrender.com/health 1-2 minutes before your pitch to wake the instance up!

---

## 3. Frontend & Landing Deployment on Vercel

### Step 1: Set the API Base URL
In rontend/index.html (and optionally landing/index.html), configure window.API_BASE_URL in the <head> script tag with your deployed Render backend URL:
`html
<script>
  // Backend API base URL for split deployment (e.g. Render backend + Vercel frontend).
  // Default empty string uses same-origin (default for local dev via ./run.sh).
  window.API_BASE_URL = "https://settlement-story-api.onrender.com";
</script>
`
*(Leave it as "" if testing locally).*

### Step 2: Deploy on Vercel
1. Go to **[Vercel Dashboard](https://vercel.com/)** -> **Add New...** -> **Project**.
2. Import your GitHub repository.
3. Leave **Root Directory** as . (repo root).
4. Leave **Framework Preset** as **Other**.
5. Build and Output Settings:
   - Build Command: *(Leave blank / disabled)*
   - Output Directory: *(Leave blank)*
6. Click **Deploy**.

Vercel automatically detects ercel.json at the repo root and routes:
- / $\rightarrow$ landing/index.html
- /app $\rightarrow$ rontend/index.html
- /fonts/* $\rightarrow$ rontend/fonts/* (with long-term immutable caching headers)
- /landing $\rightarrow$ landing/index.html

---

## 4. Local Development (Unchanged)

Local development requires zero configuration changes.

Run:
`ash
./run.sh
`
Or on Windows PowerShell:
`powershell
python backend/reset_db.py
cd backend
python -m uvicorn main:app --reload --port 8000
`
- When window.API_BASE_URL is empty or unset, all API calls automatically fall back to same-origin relative URLs (/batches, /ask, /upload, etc.).
- The backend serves the landing page at /, the app at /app, and all API routes directly.

---

## 5. Pre-Pitch Checklist

Run this single command from the repo root right before presenting to ensure your database is 100% clean and free of test clutter:

`ash
python backend/reset_db.py
`

### What this command does:
1. Deletes any dirty settlement_story.db with ad-hoc test uploads.
2. Re-initializes the database with the **12 exact seeded fixtures**.
3. Runs 	est_waterfall.py to cryptographically verify calculation invariants against all 12 fixtures.
4. Outputs [ALL PASSED] Database is clean and ready for pitch presentation!.

### Verification endpoints:
- **Health Check**: curl -s https://<your-render-url>/health $\rightarrow$ {"status":"ok"}
- **Batches Check**: curl -s https://<your-render-url>/batches $\rightarrow$ returns 12 batches
