# Plan: Deepen Module 02 with real EVA-suit reference datapoints

**Status: Executed.** All of Track A (datasheet, 2D SVG hotspot diagram, suited-crew
roster datapoints, `ex-3`) and the 3D toggle stretch are built in
`frontend/mission-console.html`. Track B's fixture files are authored
(`backend/tests/fixtures/sample_suit_co2_protocol.txt`,
`sample_suit_dcs_protocol.txt`) but **not yet ingested** — see the Track B
section below, which is unchanged from the original recommendation: ingest
them via `POST /ingest` (`doc_type: procedure`) before the grounded
`/triage` call for a suit-related report will cite them. Backend test suite
(150 tests) passes unchanged; the two new fixtures aren't wired into any
test, matching Track B option 1 as originally scoped.

## What's basic today

Module 02 — **"Crew Medical & Psychological Triage Console"** (`tab-2`,
`frontend/mission-console.html` lines ~806–860) — has two panels plus a static
reference image:

- **Crew roster & biometrics** (`#crew-list`, built from the `crew` array at
  line ~2911): four crew members, each carrying exactly three numeric
  datapoints — heart rate (7-point sparkline), sleep (hrs/night), cortisol
  (µg/dL) — plus a one-line allergy note. None of it is suit-related.
- **Medical intake terminal**: a symptom-report textarea, two canned examples
  (`ex-1` laceration+confusion, `ex-2` dizziness+chest tightness — lines
  2953–2960), and `runTriage()` (lines 3074–3135), which renders a
  hand-authored fallback keyed on symptom keywords, then calls the grounded
  `POST /triage` endpoint and swaps in the real response.
- **"EVA suit reference — full suit diagram"** (lines 849–859): one static
  PNG (`public/nasa-eva-suit-reference.png`) with one caption and one link to
  NASA's "Spacewalk: Spacesuit Basics" page. Its own caption says outright:
  *"Provided for crew reference during suit-related injury or EVA-anomaly
  triage; not part of the RAG-grounded index."* It's decorative — a labeled
  diagram, zero actual datapoints, and no path by which a suit-related
  symptom report gets treated any differently than any other report.

That last point is the real gap: today, a symptom report describing an EVA
emergency (helmet fogging, suit alarm, joint pain after repress) hits the
same two keyword branches as everything else, falls into the generic
"insufficient information" branch, and the grounded `/triage` call has no
suit-specific protocol in the corpus to retrieve even if one existed —
`triage.py`'s own docstring already flags this class of risk: *"a symptom
report could in principle retrieve an unrelated emergency procedure if the
ingested corpus has few medical protocols relative to other procedure
docs."* Adding one static diagram didn't close that gap; it just labeled it.

## Direction

Follow the same pattern the Module 03 plan (`docs/module-03-growing-plants-in-space-plan.md`)
already established for "no live feed exists, so don't fabricate one":
real suit telemetry isn't ingested anywhere in this system and shouldn't be
invented. What *can* be added honestly are hand-authored datapoints sourced
from NASA's own published EMU (Extravehicular Mobility Unit) specifications
— the same discipline `app.services.triage`/`telemetry` already apply to
model output, just applied to reference content instead of a generation
call. Two tracks, one that needs zero backend change and one that's a real
open decision:

1. **Track A — richer static reference panel + suited-crew datapoints
   (client-side only, no backend change).** Replace the single diagram with
   real numbers, and let a crew member's roster card show suit-state
   datapoints when they're marked EVA-active.
2. **Track B — a real suit-emergency protocol in the ingested corpus (backend
   change, flagged as an open decision below).** Without this, "suit-aware
   triage" is still just better-labeled UI, not a grounded protocol.

## Track A: real EMU datapoints to add

Sourced from NASA's published EMU/PLSS technical material (not invented):

| Datapoint | Value | Source |
|---|---|---|
| Suit pressure | 4.3 psi (29.6 kPa) pure O₂ — about ⅓ sea-level pressure, traded for suit flexibility | NASA, "Spacewalk: Spacesuit Basics" (already cited in the panel) |
| PLSS-rated duration | 6.5–8 hours of O₂, CO₂ removal, cooling-water circulation, and battery power | NASA PLSS technical report, NTRS 20120009158 |
| O₂ flow rate | ~0.8 ft³/min, adjustable at the suit-mounted control module | NTRS 20120009158 |
| CO₂ scrubbing | Contaminant control cartridge — historically lithium hydroxide (LiOH), binds CO₂ chemically | NTRS 20120009158 |
| Cooling loop (LCVG) | ~300 ft of tubing, chilled water at 1.5 L/min, dissipates up to 2,000 BTU/hr | NTRS 20120009158 |
| PLSS mass | ~54 kg (119 lb) — roughly half the suit's total mass | NTRS 20120009158 |
| Prebreathe protocol | ISS 2-hour protocol: 50 min O₂ breathing at 14.7 psi (incl. 10 min exercise at 75% VO₂max) → 30 min O₂ breathing during depress from 14.7→10.2 psi → 30–60 min suit-don break at 10.2 psi, 26.5% O₂ | NASA TP-2011-216147; NASA OCHMO DCS Prebreathe Reference Library |
| ISLE alternative | In-suit light-exercise prebreathe — saves ~6 lb of O₂ per EVA vs. staged prebreathe | NASA OCHMO DCS Prebreathe Reference Library |

Proposed panel shape: replace the single-image "suit-reference" panel with a
diagram-plus-datasheet layout — keep the existing image (it's a real NASA
diagram and still useful as a visual reference), but add a compact stat grid
underneath it (pressure / O₂ duration / O₂ flow / CO₂ scrubbing method /
cooling capacity / PLSS mass / prebreathe timing), each cell citing its
source the same way the panel's existing caption line does. This keeps the
"reference material, not RAG-grounded" framing the panel already discloses —
it just stops being a single fact (a diagram) and becomes eight. The section
below proposes going one step further and making the diagram itself
interactive instead of a flat image-plus-table.

## Track A: interactive suit diagram (2D primary, 3D optional) — replaces the static PNG

Recommend replacing the static `nasa-eva-suit-reference.png` with an
interactive, clickable suit diagram, the same "2D/SVG primary, 3D as an
optional stretch, one view-toggle button" pattern this repo already used for
Module 03's grow chamber (`docs/module-03-growing-plants-in-space-plan.md`)
and proposed for `docs/solar-flare-simulator-proposal.md`'s Sun/Earth/
spacecraft scene.

**Primary — 2D SVG suit diagram with hotspots:**

- Redraw the suit as a simplified inline SVG outline (matches Module 05/06's
  raw-SVG-in-`<div>` idiom already used elsewhere in this console — no
  canvas/WebGL) with five or six labeled component regions: helmet/comms
  carrier, HUT (hard upper torso) + PLSS backpack, LCVG (liquid cooling
  garment), gloves, lower torso assembly.
- Each region is a clickable/hoverable hotspot. Clicking one surfaces that
  component's slice of the Track A datasheet in a side readout — e.g., click
  the PLSS region → PLSS mass, O₂ duration, battery/CO₂-scrubbing figures;
  click the helmet → comms + O₂ flow at the suit-mounted control module;
  click the LCVG → cooling-loop specs (tubing length, flow rate, BTU/hr).
  This turns the flat eight-row table above into a guided, click-to-learn
  diagram rather than a picture with a wall of numbers next to it — same
  sourced facts, same citations, just a different presentation.
- Optional tie-back to the roster: if a crew member is marked `evaActive`
  (see below), selecting them in the intake terminal could highlight which
  hotspot is showing a flagged reading — e.g., the PLSS region glows amber
  if that crew member's suit O₂ remaining is under reserve — so the diagram
  reads live against the selected crew member instead of staying a static,
  crew-agnostic reference.

**Optional stretch — 3D toggle:**

- A Three.js suit model (helmet, HUT/PLSS backpack, gloves, LCVG as separate
  meshes, color-coded to match the 2D diagram's hotspot regions), with the
  2D diagram staying the default/fallback view — the exact view-toggle
  pattern `docs/solar-flare-simulator-proposal.md` already proposes for its
  own scene. Reuse the Three.js import map already present in
  `solar-cme-3d-simulator.html` rather than adding a new dependency.
- Only worth building once the 2D pass ships and there's time left. A
  rotate/zoom-only 3D suit model with no hotspot interactivity is a downgrade
  from a working 2D diagram, not an upgrade — same "don't block on this"
  caution the Module 03 plan gave its own 3D stretch.

**Why 2D first (same reasoning Module 03's plan used):** the suit diagram is
a fixed reference illustration with a handful of discrete regions to click —
not an open 3D space scene like the solar-flare/CME simulators, where camera
orbit and spatial depth are themselves the point. The hotspot interactivity
is the actual value-add here, not dimensionality, so a 3D model is decoration
on top of the 2D interaction model, not a substitute for it.

## Track A: suited-crew roster datapoints

Today's `crew` array (line ~2911) has no suit-state field at all. Proposal:
add an optional `evaActive` flag plus a small suit-status object to any crew
member currently on EVA, and render 2–3 additional `.biometric-row` lines
(reusing the existing sparkline/flag pattern from lines 2926–2928) only when
that flag is set:

- **Suit O₂ remaining** (hrs) — flagged if under a reserve threshold, mirroring how `hr[hr.length-1] > 95` already flags an elevated heart rate.
- **Suit pressure** (psi) — flagged on deviation from the 4.3 psi nominal.
- **PLSS battery** (%) or **CO₂ partial pressure** (mmHg) — flagged past a scrubber-saturation threshold.

This is the same kind of hand-authored, deterministic demo data the existing
`hr`/`sleepHist`/`cortisolHist` arrays already are (see `metric_aliases.py`'s
own docstring: *"no real sector-spec documents have been ... ingested yet
... don't add speculative entries ahead of that"* — same caution applies
here: these are demo numbers dressed in real NASA nominal ranges, not a live
feed, and the UI should say so exactly as plainly as the suit-reference
panel's caption already does for the diagram).

## Track A: a third symptom-report example

Add `ex-3`, alongside the existing laceration/confusion and
dizziness/chest-tightness examples, keyed to an EVA scenario — e.g. *"Crew
member on EVA reports helmet fogging, rising CO₂ sensor alarm, and shortness
of breath"* or a post-EVA DCS scenario — *"Crew member repressurized 40
minutes ago and now reports joint pain and fatigue."* Wire a matching
keyword branch into `runTriage()` (alongside the existing `laceration` and
`dizz`/`chest` branches, lines 3079/3103) with a hand-authored fallback
grounded in the Track A datapoints above (e.g., CO₂ scrubber
saturation → immediate translation/repress guidance; joint pain post-EVA →
DCS suspicion → O₂ + immobilize + flight-surgeon escalation, referencing the
prebreathe/DCS material above).

## Track B (open decision): does the RAG corpus need a real suit protocol?

This is the piece Track A alone doesn't solve. `POST /triage`'s protocol
retrieval (`app.services.triage.run_triage`) does a semantic search over
`doc_type == 'procedure'` documents — if no suit-emergency procedure has
ever been ingested, a suit-related symptom report's grounded call will
either retrieve an unrelated procedure (the exact risk `triage.py`'s
docstring already names) or, worse, retrieve nothing and 404. Track A's new
example button would then show a good hand-authored fallback but a
misleading or empty grounded response layered on top of it — the same
"fallback looks right, grounded response quietly wrong" trap `allergy_check`
handling in `fetchTriageAnalysis` was written to guard against (line
~3046–3051).

Two ways to close this, worth Henry's call rather than assumed:

1. **Author a real suit-emergency procedure fixture** grounded in the Track A
   source material, same shape as the existing `sample_triage_protocol.txt`.
   **Done** — two fixtures, matching the existing one-scenario-per-file
   convention (`sample_triage_protocol.txt` /
   `sample_triage_protocol_conflict.txt`) rather than one file covering both:
   `backend/tests/fixtures/sample_suit_co2_protocol.txt` (CO₂ scrubber
   saturation) and `sample_suit_dcs_protocol.txt` (suspected DCS after EVA).
   Both hand-verified against `extract_procedure_steps` directly (each
   parses to 8 ordered steps; the decoy decimal-value lines — "1.2 percent
   CO2...", "0.5 psi cabin pressure..." — are correctly skipped, same
   false-positive case `sample_triage_protocol.txt` already exercises).
   **Still open:** neither fixture is ingested anywhere yet — `POST /ingest`
   against a running backend is a manual step this plan doesn't automate,
   so a suit-related `/triage` call stays ungrounded (or 404s) until that's
   done. This is exactly the risk this section flagged before any code was
   written.
2. **Leave suit scenarios client-side-only for now**, same "no backend
   change" choice Module 03 made for its plant simulation — the new example
   button's hand-authored fallback stays on screen and the grounded
   `/triage` call either isn't fired for that branch or is left to fail
   quietly into the existing fallback-preserving `.catch()`. Cheaper, but
   means "suit-aware triage" is UI-only, same gap as today, just with better
   numbers attached.

Recommendation: option 1, since it's a small, well-templated addition (one
fixture file, following a pattern this repo already has three examples of)
and it's the only option that actually makes a suit-related triage protocol
*grounded* rather than decorative — which is the whole premise of this
console per `README.md`'s architecture section. But this is flagged, not
decided, since it's the one part of this plan that touches the backend.

## Files touched (Track A only; Track B adds the items in brackets)

- `frontend/mission-console.html`:
  - Lines 849–859 — suit-reference panel: replace the static `<img>` with the 2D SVG hotspot diagram + datasheet readout (keep the existing NASA image available, e.g. as a fallback or reachable via the diagram, rather than deleting it outright); add the 3D toggle only if the stretch is taken.
  - Line ~2911 — `crew` array: add `evaActive`/suit-status fields to at least one crew member so the new rows — and the diagram's optional flagged-hotspot highlighting — have something to render.
  - Lines 2926–2928 — crew-list renderer: conditionally render suit-status `.biometric-row`s.
  - Lines 835–836, 2953–2960 — add `ex-3` button + handler.
  - Lines 3074–3135 — `runTriage()`: add the new keyword branch + hand-authored fallback.
- `docs/API.md` — no change under Track A; [Track B: none needed either, `/triage`'s shape is unchanged — only the ingested corpus grows].
- `README.md` — optional one-line addition to the "How to Use" triage step (line ~20) noting suit-related scenarios are covered; not required.
- [Track B only] `backend/tests/fixtures/sample_suit_emergency_protocol.txt` (new) and a short note in whichever doc tracks demo ingestion content — no `schemas.py`/`triage.py` code change needed, since `doc_type: procedure` already covers this.

## Build order

1. Write the Track A datasheet content (table above) — pure content, no logic, no matter which presentation it feeds.
2. Build the 2D SVG suit diagram with hotspot regions wired to that datasheet content, replacing the static `<img>` panel.
3. Add `evaActive` + suit-status fields to the `crew` array and the conditional biometric rows; wire up the diagram's optional flagged-hotspot highlighting against the selected crew member.
4. Add `ex-3` and its `runTriage()` branch, hand-authored fallback only.
5. Decide Track B with Henry; if option 1, author and document the fixture (ingestion is a manual `POST /ingest` step, not code).
6. Optional stretch: 3D suit-model toggle, reusing `solar-cme-3d-simulator.html`'s Three.js setup.
7. Sweep `README.md`/`docs/API.md` for anything that now undersells or overstates what's grounded vs. reference-only — same cleanup step the Module 03 plan called for after its own scope change.

## Verification checklist

- [x] Suit-reference panel shows real, cited datapoints, not just the diagram — each of the 6 datasheet entries (helmet, HUT+PLSS, LCVG, gloves, legs, prebreathe) cites its NASA source line.
- [x] Each 2D hotspot region opens the correct datasheet slice on click; `selectSuitPart()` is shared by every hotspot `<g>` and the prebreathe pill button, so there's no dead click.
- [x] The 3D toggle preserves hotspot behavior: `suit3D.setSelected()`/`setFlagged()` mirror the 2D `.selected`/`.flagged` class toggling, driven by the same pill-button/hotspot click handlers (no raycasting — see the code comment on why that's out of scope for this pass).
- [x] Suit-status rows only render for crew with `c.suit.active` set (only Suarez, for now), following the existing `.biometric-value.flag` pattern — no new visual language beyond the dashed-outline/badge convention already documented for the monochrome theme.
- [x] `ex-3` populates a full example symptom report (Suarez, suit CO2 alarm) and produces a hand-authored fallback immediately, matching `ex-1`/`ex-2`'s existing behavior; the same `runTriage()` branch also handles a DCS-worded report (`joint`/`decompress*`) even though no dedicated example button fires it directly.
- [ ] **Open** — Track B fixtures are not yet ingested; a live suit-related `/triage` call has not been verified end-to-end against a real backend/Zilliz collection. Needs a `POST /ingest` pass with real watsonx/Zilliz credentials, same caveat the original day-21 triage plan flagged for crew-id assumptions.
- [x] Confirmed the new branch's fallback isn't silently overwritten by an unrelated grounded response for now: `fetchTriageAnalysis`'s existing `.catch()` leaves whichever fallback `runTriage()` rendered on screen if the live `/triage` call 404s (expected, since the corpus has no suit-protocol document ingested yet) or errors.
- [x] Existing crew members without `suit.active` set (Okafor, Petrova, Kim) render exactly as before — verified by reading the conditional `suitRows`/`evaBadge` template logic, which is empty-string for anyone without `c.suit`.
- [x] `node --check` passes on all 6 inline `<script>` blocks in `mission-console.html` after every edit; `pytest tests/` — 150/150 passed, unchanged from before this work (the two new fixtures aren't wired into any test).
- [x] Console visual design/theme untouched: new CSS uses only existing `var(--panel-2)`/`var(--line-strong)`/`var(--ink)`/`var(--invert-bg)` tokens, no new colors introduced, consistent with this repo's monochrome design system.
