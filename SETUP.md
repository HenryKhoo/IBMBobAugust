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
- `GEMINI_API_KEY` — optional. Only used as a third fallback tier for `/ask` generation, tried after both watsonx models have failed (e.g. a watsonx rate limit). Leave blank to skip it entirely; get a key at https://aistudio.google.com/apikey.

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

**Note:** `app.html` has `API_BASE_URL` hardcoded to the deployed Railway backend (search for `chortlechat-api-base-url` near the top of the file). To test against your local backend instead, change it to `http://localhost:8000`.

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
