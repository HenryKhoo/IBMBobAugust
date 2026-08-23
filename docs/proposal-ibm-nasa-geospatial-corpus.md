# Proposal: Fold the IBM-NASA Geospatial Catalog into ChortleChat's Corpus

## Current scope, as pitched

ChortleChat is two expert assistants in Deep Space sharing one personality dial: **Baseline**, no humor, direct, states the fact and cites the source paragraph; and **Banter**, high humor, the same fact presented as commentary with jokes. It's pitched as trained on datasets from NASA SMD and IBM Research's NASA-SMD QA benchmark, plus the `short-jokes` dataset for Banter's tone, processing everything client side, drawing from a fixed set of 117 NASA datasets.

That fixed set of NASA datasets is exactly where this proposal lands: it's the pool ChortleChat draws every citation from, and right now none of it is about NASA's own AI models.

## Why this is important to include

ChortleChat is the flagship module of an IBM-and-NASA-themed challenge, and its whole premise is grounded answers cited back to a real NASA source paragraph. Today that source pool is generic science trivia — pollution, GIS, water quality — with nothing about Prithvi, Granite Geospatial, or any of the actual AI work NASA and IBM have published together. Ask Baseline "what is Prithvi?" and the honest, correct answer is "no grounded answer for that," because nothing in the fixed dataset supports one. That's a real gap between what the module claims to be about and what it can actually talk about.

Adding the IBM-NASA Geospatial catalog closes that gap directly, on both personas at once. Baseline gets source paragraphs that are literally NASA-and-IBM AI documentation — the citation isn't just "a NASA dataset," it's the thing the whole challenge is named after. Banter gets far richer material to riff on than another pollution statistic: joint supercomputing-center backstory (Jülich, Oak Ridge), a model family named after a Roman god of transformation, satellite-to-forecast pipelines — genuinely funny, genuinely factual raw material, which matters for a persona whose entire job is finding the joke in a true thing without inventing one. And it grows the "fixed set of NASA datasets" number in the direction the pitch already claims to be pointed, rather than padding it with more of the same generic content.

## The fix, and why it's low effort

Whatever the corpus-loading mechanism turns out to be — the current backend build reads a flat `{id, type, text, domain}` JSON file (`backend/data/chortlechat_corpus.json`) via a fetch-tag-ingest script sequence (`fetch_chortlechat_corpus.py` → `tag_corpus_domains.py` → `ingest_chortlechat_corpus.py`) — the shape of this addition is the same regardless: one more source, flattened into the same document shape the pipeline already expects, with no changes needed to retrieval, the confidence threshold, or either persona's prompt.

Source material is sitting in the open: the model cards and READMEs for Prithvi-EO-1.0, Prithvi-EO-2.0-300M, Prithvi-WxC-1.0, and the IBM Granite Geospatial collection on Hugging Face are public, text-heavy, and describe exactly what a user would ask ChortleChat — what the model does, what data it trains on (HLS, MERRA-2), what tasks it's finetuned for (flood mapping, burn scar detection, crop segmentation, weather/climate downscaling), and who built it. Turn each model card's sections into documents the same way the existing fetch script turns benchmark paragraphs into documents, tag them into the domain scheme, and ingest.

## Where it lands in the existing domain scheme

Most of this content maps onto domains that already exist, so no schema change is needed: Prithvi-WxC and MERRA-2 weather/climate content fits Climate Reconstruction; flood- and burn-scar-mapping use cases fit Environmental Hazards; anything that's really about the models themselves — architecture, training data, the IBM/NASA/ORNL/Jülich collaboration story — is a legitimate Other, the existing catch-all. No new domain, no domain-picker UI change.

## Two cheap add-ons once the corpus lands

Add a handful of suggested chips per domain — "What is Prithvi-WxC trained on?", "What does Prithvi-EO-2.0 do differently from 1.0?" — so users find the new content instead of stumbling into it. And since these source documents have stable, citable URLs (the model card itself), consider having the citation for this batch link straight to the Hugging Face page instead of an internal chunk reference, so "cites the source paragraph" becomes a clickable source.

## A discrepancy worth flagging, separately from this proposal

The pitch copy above (client-side processing, training on `short-jokes`, 117 datasets) describes a different architecture than the backend as currently built, which runs server-side retrieval against Zilliz with watsonx.ai generation over 87 documents, and gives Banter its tone through a prompt instruction rather than fine-tuning on a jokes dataset. That's not something this proposal changes or depends on — the corpus-expansion approach above works the same way regardless of which description is the one that ships — but it's worth reconciling the pitch and the build before demo day so the two tell the same story.

## What this deliberately does not include

Actually running Prithvi-EO or Prithvi-WxC inference — feeding ChortleChat a satellite scene or a MERRA-2 slice and having it segment or forecast — is a real capability upgrade but not a low-effort one: it needs a model runtime, GPU inference, HLS/MERRA-2 data access, and a new endpoint and UI affordance that don't exist today. That's a legitimate stretch goal for later, but a different scope of work from closing the gap between what ChortleChat claims to be about and what it can currently cite.

## Net effect

One new source, folded into the pipeline the same way every other source already is, turns ChortleChat from a module that can't answer the central question of its own challenge theme into one whose citations point at the actual IBM-NASA work it's supposed to be showcasing — the highest ratio of narrative and demo impact to effort available right now.
