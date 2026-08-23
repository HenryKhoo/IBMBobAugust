# The North Star — IBM Bob August Challenge

_Sailors used the North Star to find their bearing when everything else was uncertain. This project does the same job for a real question about space science, turning it into one clear, grounded answer instead of a guess._

Challenge theme: Reimagine Space Exploration with AI

## Motivation

The North Star is the landing page for **Talkback**, a grounded NASA Earth-science Q&A console. Ask a real question in plain English — tropical cyclones, dust storms, drought, wildfires, and more — and Talkback answers from a real NASA source passage, cites where that answer came from, and says so honestly when nothing in its corpus supports an answer, rather than guessing. Two voices are available: **Baseline**, direct and no-commentary, and **Banter**, the same fact told with personality. Persona only changes how a true thing is said, never whether it's said or what it claims. Built for the IBM Bob AI Builders Challenge (August theme: *Reimagine Space Exploration with AI*).

## How to Use

1. Open the North Star landing page for the pitch, the Technology & Modules breakdown, the Mission, and the Team.
2. Click **Launch Talkback** to open the console.
3. Pick a persona — Baseline or Banter. Banter unlocks a humor slider; Baseline ignores it.
4. Ask a question, or pick one of the suggested chips.
5. Read the answer: a grounded response carries a confidence score and a source citation back to the passage it came from; an unmatched question gets an honest "no grounded answer" instead of a fabricated one.

## Demo

Demo video: [add the demo video link]

## AI Approach and Architecture

### Retrieval-augmented generation — IBM Granite embeddings + Zilliz

NASA SMD Q&A benchmark passages are chunked and embedded with IBM's Granite embedding model on watsonx.ai, then indexed in Zilliz Cloud (managed Milvus) as `science_reference` documents. Every answer Talkback gives is generated from a passage retrieved from that index, never from the model's own memory, which is what keeps every response traceable back to a real source instead of a guess.

### Grounded generation — IBM watsonx.ai

1. Retrieve the single best-matching passage for the question.
2. Convert its cosine similarity to a `[0, 1]` confidence score. Below a 0.68 threshold, both personas return an honest no-match response instead of guessing.
3. Above threshold, a Granite/Mistral instruct model on watsonx.ai generates the grounded answer exactly once, always in Baseline's voice, strictly from the retrieved passage.
4. If Banter is selected, it re-tells that already-generated, already-grounded answer in its own tone — it never answers the question itself and is explicitly instructed to introduce no new fact, number, or claim. This is what keeps "honesty is not a dial" a property of the code, not just a prompting convention.
5. Every grounded answer carries a source reference line back to the document and chunk it came from.

### API surface

`GET /health` — reports whether the required watsonx/Zilliz credentials are actually configured, not just that the process is running. `POST /ingest` — chunk, embed, and upsert documents into Zilliz. `POST /query` — retrieval only, for inspecting the actual source passages a question matches. `POST /ask` — the main Q&A endpoint described above.

## Quickstart

```bash
git clone https://github.com/HenryKhoo/IBMBobAugust.git
cd IBMBobAugust/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # fill in WATSONX_* and ZILLIZ_* credentials
uvicorn app.main:app --reload --port 8000
```

Then serve `frontend/` with any static file server (e.g. `python3 -m http.server 5500`) and open `app.html`. See [SETUP.md](SETUP.md) for full setup, environment variable details, and the git workflow.

## How IBM Bob was used

This project was built with **IBM Bob** as our AI coding assistant throughout, used for writing new code, debugging errors, scaffolding the backend, and reviewing changes across the FastAPI service and the console frontend. It sat alongside the actual watsonx.ai/Granite stack that powers the product itself, functioning as our day to day development environment.
