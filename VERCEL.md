# Vercel Deployment Reference (Frontend + Landing)

## Dashboard Settings

| Field | Value | Notes |
|---|---|---|
| **Framework Preset** | Other | Static HTML project |
| **Root Directory** | . | Root of repository |
| **Build Command** | *(None)* | No compilation or bundling required |
| **Output Directory** | *(None)* | Served directly by Vercel |

## Routing & Rewrites (ercel.json)

Vercel reads ercel.json at the repo root:
- / $\rightarrow$ landing/index.html (Explainer/Marketing page)
- /app $\rightarrow$ rontend/index.html (Main interactive application)
- /landing $\rightarrow$ landing/index.html
- /fonts/* $\rightarrow$ rontend/fonts/* (Cached immutably for 1 year)

## Connecting to Backend API

Open rontend/index.html and update the <script> tag near the top of <head>:

`html
<script>
  window.API_BASE_URL = "https://your-render-service.onrender.com";
</script>
`

If left empty (""), the application falls back to same-origin relative URLs for local development.
