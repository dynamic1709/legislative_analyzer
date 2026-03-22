# AI Legislative Analyzer

 An end-to-end web app that helps citizens understand Indian legislative PDFs using retrieval + citation-aware generation, with multilingual output.

## What it does
- Upload a legislative PDF (Act/Bill/Policy).
- The backend extracts text, chunks it by structure, compresses the context, and indexes it.
- You ask a question (“What does this law mean for me?”) and the system retrieves the most relevant clauses and generates a simple explanation with citations.
- Output can be translated to an Indian language (English-in, localized-out).

## Demo flow (recommended for judges)
1. Open the app.
2. Complete the citizen profile (profession/education/region).
3. Upload a PDF.
4. Ask 2–3 questions (e.g., obligations, penalties, definitions).
5. Switch output language and ask again.

## Key features
- **Hybrid retrieval**: semantic + BM25 + RRF fusion for better clause matching.
- **Token optimization**: compresses retrieved context to keep prompts small.
- **Citation-aware answers**: prompts the model to end factual sentences with citations.
- **Guardrails**: if the model fails / times out, the API still returns a useful clause-based fallback.
- **Citizen personalization**: explanation style adapts to profile fields.

## Measurable results (token compression)
These numbers are produced by the pipeline and stored with each uploaded document.

- Example: “IT Act 2000 Updated”
  - Original tokens: **25,926**
  - Compressed tokens: **2,394**
  - Tokens saved: **23,532**
  - Compression: **90.77%** (≈ **10.83×** smaller prompt footprint)

Tip: after running queries, you can inspect latency instrumentation via `GET /metrics/latency`.

## Tech stack
- **Backend**: FastAPI (Python)
- **Frontend**: React + Vite
- **Vector store**: ChromaDB (local persistent store)
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2`
- **LLM**: Google Gemini (default) or OpenAI (configurable)
- **Translation**: `deep-translator`

## Repository structure
```
ai-legislative-analyzer/
  backend/                 # FastAPI API + pipelines
    main.py
    services/
    data/                  # lightweight JSON state (documents registry, etc.)
  frontend/                # React UI
  RUN.md                   # quick run notes
  README.md                # this file
```

## Setup (Windows / PowerShell)
### Prerequisites
- Python 3.10+ (recommended)
- Node.js 18+
- A Gemini or OpenAI API key

### 1) Backend
From the repo root:
```powershell
# create + activate venv (if you don't already have one)
python -m venv .venv
& .\.venv\Scripts\Activate.ps1

# install backend deps
pip install -r backend\requirements.txt

# run the API
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
The API will be available at `http://127.0.0.1:8000`.

### 2) Frontend
In a second terminal:
```powershell
cd frontend
npm install
npm run dev -- --port 3000
```
Open `http://localhost:3000`.

The frontend proxies `/api/*` → `http://localhost:8000/*` via Vite.

## Deploy (Vercel)
This repo is a **monorepo** (frontend + FastAPI backend). Vercel is a great fit for the **frontend**.

Because the backend uses Chroma persistence + ML models (and can take longer than typical serverless timeouts), the most reliable setup is:
- Deploy **frontend** on Vercel
- Deploy **backend** on a long-running host (Render / Railway / VM)

### 1) Deploy the backend (recommended)
Deploy the FastAPI app on any host that supports long-running Python services.

Start command (from the repo root):
- `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`

Make sure your backend is publicly reachable, e.g.:
- `https://your-backend.example.com`

### 2) Deploy the frontend on Vercel
1. Push this repo to GitHub (done).
2. In Vercel: **New Project** → import `ai-legislative-analyzer`.
3. In **Project Settings**:
  - **Root Directory**: `frontend`
  - **Build Command**: `npm run build`
  - **Output Directory**: `dist`
4. Add an Environment Variable (Vercel → Project → Settings → Environment Variables):
  - `VITE_API_BASE` = `https://your-backend.example.com`
    - No trailing slash.
5. Deploy.

After this, the frontend will call the backend using `VITE_API_BASE` in production.

### Backend on Vercel (practical option: proxy)
Running this Python backend *directly* on Vercel serverless is usually not reliable because it includes heavy native dependencies (`opencv-python`, `pytesseract`), persistent Chroma storage, and model downloads.

Instead, this repo includes a Vercel Serverless Function proxy at:
- `api/[...path].js`

That means your deployed Vercel app can serve:
- Frontend (static)
- `/api/*` (serverless proxy) → forwards to your real backend host

To use it:
1. Deploy the **real backend** to Render/Railway/VM.
2. In Vercel → Project → Settings → Environment Variables:
  - `BACKEND_URL` = `https://your-backend.example.com`
3. Keep `VITE_API_BASE` **unset** (or empty) so the frontend uses same-origin `/api/*`.

## Environment variables
Create a `.env` file (repo root) or set env vars in your shell.

Required (pick one provider):
- `AI_PROVIDER=google` and `GOOGLE_API_KEY=...`
- OR `AI_PROVIDER=openai` and `OPENAI_API_KEY=...`

Optional tuning:
- `LLM_TIMEOUT_SECONDS` (default `20`)
- `NLI_TIMEOUT_SECONDS` (default `1.5`)
- `CITATION_RETRY_THRESHOLD` (default `0.6`)
- `CITATION_HARD_BLOCK_THRESHOLD` (default `0.2`)

## Notes / troubleshooting
- **First run downloads models**: `sentence-transformers` and (optionally) the NLI verifier may download weights on first use.
- **If the LLM is unavailable** (no key, network, timeout), the API returns a clause-based fallback so you still get an answer.
- This tool provides **explanations**, not legal advice.

## API quick check
- Health: `GET /health`
- Upload: `POST /upload` (multipart)
- Ask: `POST /query`

---
If you want, tell me your hackathon’s judging criteria (max 3 bullets) and I’ll tailor the README’s “Why this matters” section to match it (without changing the app).