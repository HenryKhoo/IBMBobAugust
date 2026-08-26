# Partner Setup — The North Star

## Prerequisites
- Python 3.11+
- Git
- A modern browser (frontend is static HTML — no Node/npm required)

## 1. Clone

```bash
git clone https://github.com/HenryKhoo/IBMBobAugust.git
cd IBMBobAugust
```

## 2. Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Environment variables

```bash
cp .env.example .env           # from repo root
```

Fill in `.env` with:
- `WATSONX_API_KEY`, `WATSONX_PROJECT_ID` — IBM watsonx.ai credentials
- `ZILLIZ_URI`, `ZILLIZ_TOKEN` — Zilliz Cloud (Milvus) credentials
- `GEMINI_API_KEY` — optional, embeddings/retrieval only (see `backend/app/services/watsonx.py`). Generation (`/ask`'s instruct model) is always watsonx. When set, embeddings switch from watsonx/Granite to Gemini's `gemini-embedding-001` — a full replacement, not a fallback, since embeddings from different providers can't safely mix — and retrieval switches to a separate Zilliz collection (`ZILLIZ_COLLECTION_NAME_GEMINI`) that has to actually be populated first. Leave blank to keep watsonx/Granite embeddings. `GEMINI_API` is also accepted as an alternate name. Get a key at https://aistudio.google.com/apikey.
- If you do set `GEMINI_API_KEY`, run `python backend/scripts/ingest_cosmos_corpus.py` once (from `backend/`, venv active, `.env` configured) before asking any real questions — it re-embeds the existing corpus with Gemini and populates `ZILLIZ_COLLECTION_NAME_GEMINI`. The corpus is already fetched locally at `backend/data/cosmos_corpus.json`, so this doesn't hit NASA/HuggingFace again, just Gemini + Zilliz.

Ask Henry for these values — they're not in the repo.

## 4. Run the backend

```bash
# from backend/
uvicorn app.main:app --reload --port 8000
```

Check it's up: http://localhost:8000/health

## 5. Run the frontend

No build step — it's plain HTML/JS.

```bash
cd frontend
python3 -m http.server 5500
```

Open http://localhost:5500/ for the landing page, or http://localhost:5500/app.html to go straight to the console.

**Note:** `app.html` has `API_BASE_URL` hardcoded to the deployed Railway backend (search for `cosmos-api-base-url` near the top of the file). To test against your local backend instead, change it to `http://localhost:8000`.

## 6. Git workflow

```bash
git pull origin main
git checkout -b your-branch-name
# ...make changes, commit...
git push origin your-branch-name
# open a PR
```

## Good to know
- No `package.json` — don't run `npm install`, there's nothing to install for the frontend.
- Never commit `.env` (already gitignored).
- Run backend tests with `pytest` from `backend/`.
