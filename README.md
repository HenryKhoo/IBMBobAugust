# The North Star — IBM Bob August Challenge

_Sailors used the North Star to find their bearing when everything else was uncertain. This console does the same job for a crew in a crisis, turning noisy telemetry, scattered symptoms, and shifting supply numbers into one clear, grounded answer._

Challenge theme: Reimagine Space Exploration with AI

## Motivation

The North Star is an operations console for a deep space habitat. A crew in a
crisis does not need more raw data, it needs a clear read on what the data
means and what to do next. The console watches live telemetry, crew
biometrics, and supply levels, and turns each one into a short, grounded
answer a crew member can act on immediately. Built for the IBM Bob AI
Builders Challenge (August theme: *Reimagine Space Exploration with AI*).

## How to Use

1. **Watch the crisis timeline** — the console reads the live event feed, isolates the event that matters, and builds the matching emergency procedure step by step.
2. **Read the telemetry translator** — each life support sector gets a plain language read on its status, with a confidence score and a line showing what the reading is grounded in.
3. **Run a triage** — describe a crew member's symptoms in plain English, and the console cross references their biometrics and file for an immediate, grounded triage protocol.
4. **Simulate rationing** — trigger a supply shortfall and adjust the ration and resupply window to see a survival probability and a grounded recommendation.
5. **Ask a question** — search the mission log and procedure library directly, and get an answer sourced back to the passage it came from.

## Demo

Demo video: [add the demo video link]

## AI Approach and Architecture

### Retrieval-augmented generation — IBM Granite embeddings + Pinecone

Mission documents, including emergency procedures, sector specifications, crew files, and prior incident records, are chunked, embedded with IBM's Granite embedding model on watsonx.ai, and indexed in a Pinecone serverless vector database. Every generated answer, whether it is a telemetry summary, a crisis root cause, a triage protocol, or a rationing plan, is answered from passages retrieved from that index rather than the model's own memory. This keeps every AI response traceable back to a real source document instead of a guess.

### Grounded decision support — IBM watsonx.ai

Each module is backed by a small, focused pipeline:

1. **Retrieve** — pull the passages relevant to the current sector, event, symptom report, or supply state.
2. **Generate** — a Mistral or Granite instruct model on watsonx.ai turns the retrieved passages and live state into a plain language answer.
3. **Score** — a confidence value is derived from real signals, such as retrieval strength or distance from a nominal band, never a random number.
4. **Cite** — every answer carries a source reference line back to the document it was grounded in.

## How IBM Bob was used

This project was built with **IBM Bob** as our AI coding assistant throughout, used for writing new code, debugging errors, scaffolding the backend, and reviewing changes across the FastAPI service and the console frontend. It sat alongside the actual watsonx.ai/Granite stack that powers the product itself, functioning as our day to day development environment. A `CLAUDE.md` file in this repository sets the ground rules IBM Bob follows here, including keeping the console's existing visual design untouched and grounding every AI response in retrieved documents rather than generated guesses.
