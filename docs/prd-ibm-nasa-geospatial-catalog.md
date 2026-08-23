# PRD: IBM-NASA Geospatial Catalog for ChortleChat

**Status:** Proposed — not started
**Target release:** Before final demo/submission (owner to confirm exact date against the challenge deadline)
**Owner:** Henry Khoo
**Module affected:** ChortleChat (Baseline + Banter)

## Team goals and business objectives

Make ChortleChat able to answer, correctly and with a real citation, the question its own challenge is named after: what NASA and IBM have actually built together in AI for Earth observation. Today it can't — the objective is to close that specific gap before judging, not to expand scope generally.

Concretely: every hand-written question about Prithvi-EO, Prithvi-WxC, or IBM Granite Geospatial should return a grounded, cited answer from both personas, using the existing retrieval pipeline and confidence threshold, with no new architecture and no changes to how Baseline or Banter are prompted.

## Background and strategic fit

ChortleChat's premise is a grounded NASA Q&A console: Baseline states a fact and cites the source paragraph it came from, Banter retells the same fact with humor and invents nothing new. That premise depends entirely on what's in its fixed dataset. Right now that dataset is generic science trivia — pollution, GIS, water quality — flattened from the NASA-SMD QA benchmark, and contains nothing about NASA's own AI models or the IBM collaboration the challenge is built around. Ask either persona "what is Prithvi?" today and the honest, correct answer is the no-match fallback, because nothing in the corpus supports one.

This directly undercuts the pitch: a module billed as showcasing IBM-and-NASA AI collaboration currently can't say anything grounded about that collaboration. Strategically, this is the single highest-leverage content gap to close before demo day — it doesn't require new infrastructure, new personas, or a new domain, only new source material flowing through the pipeline that already exists.

## Assumptions

The Hugging Face model cards and READMEs for Prithvi-EO-1.0, Prithvi-EO-2.0-300M, Prithvi-WxC-1.0, and the IBM Granite Geospatial collection are stable enough at build time to fetch once and commit, the same way the existing NASA-SMD corpus is fetched once and committed rather than pulled live.

The existing five-domain taxonomy (Tropical Cyclone Dynamics, Saharan Dust, Climate Reconstruction, Environmental Hazards, Other) is assumed sufficient to classify this new content without adding a sixth domain or touching the domain-picker UI.

The existing confidence threshold and embedding approach are assumed to generalize to this new content without retuning, since it's the same style of descriptive/technical passage as the current corpus — this should be spot-checked once real documents are ingested, not assumed permanently true.

Whichever corpus-loading mechanism ships for demo day — the currently-built server-side fetch/tag/ingest pipeline, or the client-side, fixed-dataset design described in the current pitch copy — is assumed able to accept one more source in the same `{id, type, text, domain}` shape without a redesign. This proposal doesn't take a position on reconciling those two descriptions (see Questions below); it only depends on whichever one ships being able to add a source.

Redistributing model-card text as embedded reference passages is assumed to be license-compatible; this should be confirmed per repository, not assumed blanket-clear, before anything ships.

## User stories

**As a judge or first-time user evaluating the challenge submission**, I want to ask ChortleChat something concrete about Prithvi or Granite Geospatial and get a grounded, cited answer, so that the module visibly delivers on its own premise. Success metric: at least 8 of 10 hand-written Prithvi/Granite/HLS/MERRA-2 test questions return a grounded (non-fallback) answer at or above the confidence threshold.

**As a user in Banter mode**, I want the same underlying fact delivered with humor drawn from genuinely interesting IBM-NASA material (joint supercomputing centers, model naming, satellite-to-forecast pipelines), not another pollution statistic, so that the persona's commentary has something worth joking about. Success metric: Banter's re-told answer for each of the above test questions still passes the existing no-new-facts check — same claims as Baseline, different voice.

**As a user browsing by domain**, I want relevant suggested chips (e.g. "What is Prithvi-WxC trained on?") to appear under Climate Reconstruction and Environmental Hazards, so I discover this content without needing to already know it exists. Success metric: each of those two domains gets at least two new chips referencing the added content.

**As a developer maintaining the corpus**, I want this new source added as a repeatable fetch step in the same shape as the existing one, so a future Prithvi or Granite release can be folded in the same way without re-architecting ingestion. Success metric: a new fetch script exists, runs standalone, and its output passes through the existing tag and ingest steps unmodified.

## User interaction and design

No new screens, no new domain, no change to the persona toggle or humor slider. The only user-visible changes are: new answerable questions surfacing under existing domain chips, and — as an optional second-pass polish, not required for this PRD's core scope — citations for this batch of content linking to the actual Hugging Face model card instead of an internal chunk reference, if the citation renderer supports a link in that slot. No wireframes are needed for either change; both fit the console's existing citation and chip layout as-is.

## Questions

| # | Question | Why it matters |
|---|---|---|
| 1 | Which sources exactly: all four models (Prithvi-EO-1.0, EO-2.0-300M, WxC-1.0) plus the Granite Geospatial collection, or a curated subset for time's sake? | Scopes how much fetch/tagging work this actually is before demo day. |
| 2 | Should model-card text be used close to verbatim, or rewritten into the existing paragraph-plus-Q&A shape the current corpus uses? | Verbatim is faster; matching the existing shape may retrieve and read more consistently. |
| 3 | Is per-repository licensing on Hugging Face confirmed compatible with embedding this text as reference passages in a public repo? | Needs a yes before anything ships, not after. |
| 4 | Does the confidence threshold (0.68) hold up against real Prithvi/Granite test questions, or does this content need its own spot-check? | Determines whether any threshold or retrieval tuning is needed post-ingest. |
| 5 | The current landing-page pitch describes client-side processing, training on the `short-jokes` dataset, and a fixed set of 117 datasets — none of which match the currently-built server-side pipeline over 87 documents with prompt-based Banter tone. Which description is the one the team wants true by demo day? | Doesn't block this proposal, but affects what claim gets made on stage and should be resolved separately. |
| 6 | Does the frontend's citation renderer currently support a clickable link, or only plain text? | Determines whether the "link to the real model card" polish item is in scope or needs its own small frontend change. |

## What we're not doing

Not running Prithvi-EO or Prithvi-WxC inference — no feeding ChortleChat a satellite scene or a MERRA-2 slice for it to segment or forecast. That's a genuine capability upgrade, but it needs a model runtime, GPU inference, and real HLS/MERRA-2 data access, plus a new endpoint and UI affordance that don't exist today. It's a reasonable stretch goal for a later pass, explicitly out of scope here.

Not adding a sixth domain, not changing the domain-picker UI, and not touching the persona prompts, the confidence threshold's underlying logic, or the memory/session system. This PRD is scoped to one thing: get IBM-NASA geospatial content into the existing pipeline so both personas can answer the challenge's own subject matter.
