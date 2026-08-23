# Proposal: ChortleChat Enhancements

Web application: The North Star — ChortleChat module (IBM Bob August Challenge, "Reimagine Space Exploration with AI").

## 1. Team

Author: Henry Khoo, Laura Lai

### References
Add these references to index.html under Team section.

* APA 7th Edition: Tony, L. A., Ganesan, H., Sangeetha, G. R., Amritha, A., Durairaj, R., Chaman, J. J., & Padmakumar, E. S. (2025). Building a standalone AI assistant for deep space exploration. *Space Education and Strategic Applications*, 5(2), 43–57. https://doi.org/10.18278/sesa.5.2.7
* Dataset 1: Fraser, "Short jokes dataset," Hugging Face, [Online]. Available: https://huggingface.co/datasets/Fraser/short-jokes. [Accessed: Aug. 23, 2026].
* Dataset 2: NASA IMPACT, "NASA SMD QA benchmark dataset," Hugging Face, [Online]. Available: https://huggingface.co/datasets/nasa-impact/nasa-smd-qa-benchmark. [Accessed: Aug. 23, 2026].
* Film: C. Nolan, Director, *Interstellar*. Paramount Pictures / Warner Bros. Pictures, 2014.

## 2. Software Improvement Design

Modeled on Tony et al. (2025)'s standalone deep-space AI assistant, a longer-horizon version of ChortleChat would move from a hosted web console to a modular, offline-first pipeline orchestrated via ROS nodes running on a Linux edge device — the deployment target a real deep-space assistant needs, where a network connection back to a server can't be assumed.

Voice input would run through a lightweight offline ASR model (Kaldi TDNN or Whisper Edge), with a central manager separating system commands (health checks, media display) from conversational queries so the two don't compete for the same response path. The dialogue engine itself would be hybrid: a lightweight classifier/neural network handles low-latency responses, a RAG pipeline (via LangChain) backed by a local vector database indexes custom manuals and mission reference material, and a quantized local LLM (LLaMA-3 or Vicuna-7B class) handles open-ended interaction — the same retrieve-then-generate discipline ChortleChat already follows, just running entirely on-device instead of against watsonx.ai and Zilliz Cloud. Text responses would be piped into a local DNN-based TTS system, synchronized with a PyGame or OpenGL lip-sync module for a visual, interactive rendering of the assistant, rather than the current text-only console.

This design prioritizes low latency, resource efficiency, and total independence from external network access — properties the current web-hosted build doesn't need, but that matter if ChortleChat's premise (a deep-space assistant) is ever taken to an actual embedded or field deployment rather than a browser demo.

## 3. Database Enhancement Design

Add a new source to ChortleChat's corpus: the Hugging Face model cards and READMEs for Prithvi-EO-1.0, Prithvi-EO-2.0-300M, Prithvi-WxC-1.0, and the IBM Granite Geospatial collection. These are stable enough at build time to fetch once and commit, the same way the existing NASA-SMD corpus is fetched once and committed rather than pulled live — no new fetch-time dependency, no live external calls at runtime, just one more static source flowing through the same fetch-tag-ingest pipeline the current corpus already uses.

This closes a real gap: ChortleChat's fixed dataset currently has nothing about NASA's own AI models or the IBM collaboration the challenge is named after, so a question like "what is Prithvi?" returns the honest no-match fallback today. Adding this source gives both personas real, citable material to draw from — Baseline gets a genuine source paragraph to cite, Banter gets material worth joking about — without any change to retrieval logic, the confidence threshold, or either persona's prompt.

## Conclusion and Overview

**Software improvement (Section 2) impact:** This is an architectural pivot, not an incremental change — it takes ChortleChat off a hosted web stack entirely and onto an offline, edge-deployed assistant with voice and visual interaction. The payoff is a genuinely deployable, network-independent deep-space assistant that matches the challenge's own framing more literally than a browser console does; the cost is a full new engineering track (ROS integration, on-device ASR/TTS, a quantized local LLM, lip-sync rendering) that doesn't reuse the current FastAPI/Zilliz/watsonx.ai build. Treat this as a future-state direction to plan toward, not a near-term deliverable.

**Database enhancement (Section 3) impact:** This is the opposite profile — small, immediate, and low-risk. It reuses 100% of the existing ingestion pipeline, touches no application code, and can ship before the next demo. The payoff is direct and visible in every demo run afterward: ChortleChat can finally answer, with a real citation, the central question its own hackathon theme is built around.

Together, the two enhancements sit at opposite ends of the same roadmap: the database enhancement is the right next step to make immediately, and the software improvement is the right longer-term direction to point the project toward once the current build has proven itself.
