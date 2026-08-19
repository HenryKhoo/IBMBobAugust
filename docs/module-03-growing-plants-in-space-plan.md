# Plan: Replace Module 03 with "Growing Plants in Space"

## What's being replaced

Module 03 is currently **"Supply Chain, Resource Scarcity & Rationing Predictor"** (`tab-3` in `frontend/mission-console.html`, line ~850) — an abstract kcal-rationing calculator. The crew triggers a "hydroponics crop failure," drags a ration/resupply-window slider, and gets a survival-probability number and a chart, with the narrative text generated server-side from a RAG lookup (`POST /rationing/simulate`).

The retitled module keeps the same tab slot and the same underlying crisis (hydroponics failure) but turns it into what it was always gesturing at: an actual plant-growth simulation, grounded in NASA's real Veggie / Advanced Plant Habitat (APH) / BRIC-LED research (source material: the NASA "Growing Plants in Space" / "Station Science 101: Plant Research" articles supplied for this task).

## Direction: self-contained, no backend (per your call)

**Decision:** drop the RAG/backend integration entirely. Module 03 becomes a **client-side-only simulator**, matching Modules 05 and 06 ("Try It Yourself — Retiring a Dead Satellite," "Protect Our Planet," "DART Navigator," "Solar Flare Simulation") rather than the grounded-AI pattern the other four modules use.

This repo already has the exact template for this: Module 05's tab carries an explicit disclaimer note —

> "How to play — this module is a hands-on simulation, not backed by live telemetry or the retrieval pipeline the rest of this console uses."

— and its logic lives entirely in a self-contained `(function(){ ... })()` IIFE block with no `fetch()` calls, driven by local JS state and SVG (e.g. the deorbit simulator's orbital-mechanics math at lines ~3973–4188). Module 03 follows the same shape.

**What this simplifies:**
- **Zero backend changes.** `backend/app/services/rationing.py`, its schemas, its endpoint, and `backend/tests/test_rationing.py` are left completely untouched — nothing in the plan below touches them. `POST /rationing/simulate` keeps existing and keeps passing its tests; it's simply no longer called by the frontend.
- **No new grounding documents to ingest**, no prompt template, no `docs/API.md` endpoint entry.
- **No "is this endpoint grounded correctly" testing burden** — the module's only correctness bar is "does the client-side simulation behave the way the UI says it does," same as Module 05/06 today.

**What still needs a copy fix:** `README.md`'s architecture section currently claims every generated answer — "whether it is a telemetry summary, a crisis root cause, a triage protocol, or a rationing plan" — is RAG-grounded. Once Module 03 is self-contained, that list should drop "a rationing plan" (down to three grounded modules: telemetry, crisis, triage), and README's "How to Use" step 4 needs to describe the new plant simulation instead of triggering a supply shortfall.

## Current cross-links that must survive

These are all pure client-side JS already — none of them depend on the `/rationing/simulate` backend call, so dropping the backend doesn't put them at risk:

- **Module 01 → Module 03 (water):** `waterMonthlyLossFromRate()` derives the water resource card's depletion slope live from Module 01's water-recycler `rate`. A grow chamber needs water too, so this becomes the plant irrigation draw instead of a generic "water resource" — keep the function, retarget its caption text.
- **Module 02 → Module 03 (medicine):** checking a Kit-A/Kit-B-tagged triage step calls `adjustMedicineKit()`, which decrements a kit and fires an alert banner reading `"Supply risk — Module 03"` in the triage view (line ~3071). Medicine/Kit A/B tracking is orthogonal to plants and stays untouched, including that banner string (still accurate — it's still Module 03).
- **`btn-trigger-crop-failure` / `btn-reset-supply`:** the existing trigger/reset affordance is the natural hook point — "trigger crop failure" becomes "diagnose and recover the crop failure" instead of "do rationing math about it."
- **`setModuleAlert('t4', ...)` / `logIncident('T4', ...)`:** the alert-banner and incident-log integration (shared across all tabs) stays; only the copy changes (e.g. "Crop Failure — Recovery In Progress" instead of "Food Supply Shortfall Risk").
- **Spare parts card:** currently a generic cartridge counter whose draw rate is coupled to the crop-failure event (`sideResources[2].extraLoss`). Keep as-is, or fold "grow-light LED cartridges / nutrient cartridges" into its label — minor, low-risk either way.

## New module content (grounded in the NASA source material)

Since there's no backend RAG call, "grounded" now means the simulation's rules and copy are drawn from real documented NASA findings rather than invented — the accuracy discipline moves from a retrieval pipeline into how the sim logic and on-screen text are written. Facts to build from:

- **Veggie**: carry-on-luggage-sized chamber, 6 plants, root "pillows" (clay media + fertilizer) that balance water/nutrients/air against microgravity's tendency to form air or water bubbles around roots.
- **Veggie PONDS**: swaps the pillow for a small water reservoir — a concrete "upgrade" the sim can let the user pick.
- **Advanced Plant Habitat (APH)**: enclosed, automated, 180+ sensors, six-color LED array (red/green/blue/white/far-red/infrared), controlled-release fertilizer in a porous clay substrate — a "hands-off, high-instrumentation" alternative to Veggie.
- **Light**: plants grow on red + blue wavelengths; green is added only so the produce looks normal to the crew (the real chamber glows magenta-pink). A light-spectrum control is a natural, visually strong interactive element.
- **Real failure mode already documented**: Scott Kelly's Veggie zinnias got overwatered, airflow was poor, and fungus took hold — he manually cleaned and nursed them back to flower. This is the literal, sourced version of "hydroponics crop failure" the sim already simulates, so the diagnosis step (overwatering / airflow / light / nutrient) can be built directly from this incident.
- **Crops actually grown**: lettuce (3 types), Chinese cabbage, mizuna mustard, red Russian kale, zinnias, dwarf wheat, Arabidopsis, chile peppers (PH-04), tomatoes, radishes — good source list for a crop-picker.
- **Nutrition angle**: fresh produce is needed because packaged-food vitamins (esp. vitamin C) degrade over long-duration missions — echoes the scurvy reference in the source text, ties the module back to crew-health stakes the way the old kcal-survival number did.
- **Bonus/stretch facts**: lignin-and-microgravity structural question (APH/Arabidopsis-GRO), immune-gene suppression + the flag-22 "trick the plant into defending itself" BRIC-LED experiment, transplanting sprouts to save a struggling pillow (VEG-03), epigenetic inheritance across generations (PH-03).

A short static reference list of these facts (not a live document store) is enough — e.g. a small JS object mapping diagnosis choices / light settings to outcome text, hand-written from the source material, the same way Module 05/06's outcome banners are hand-written rather than model-generated.

## Interactive simulation design (2D/3D)

**Recommendation: 2D/SVG chamber view, not a 3D scene.** The existing 3D asset in this repo (`solar-cme-3d-simulator.html`, Three.js/orbit-camera) is built for wide-open orbital space — Sun/Earth/spacecraft at planetary scale. A grow chamber is a small enclosed box with a dense LED array and six plant pillows in a grid; that's a natural fit for the console's existing SVG idiom — Module 05/06 build their whole interactive scene in raw SVG/DOM inside a `<div id="...-stage">` mount, no canvas or WebGL — and keeps the module visually consistent with the rest of the console rather than introducing a second heavyweight rendering stack. 3D is offered below as an optional stretch, not the default.

**Primary view — 2D grow-chamber cross-section (SVG, in-page, matches console style):**
- A chamber rectangle containing a 2×3 (or 6-slot) pillow grid, each slot rendered as a small plant icon whose size/color reflects its health (healthy green → wilting yellow → fungal-brown, matching the Kelly-zinnia failure mode).
- An LED bar along the top whose glow color responds live to a light-spectrum control (red/blue mix slider → chamber genuinely tints magenta-pink at the NASA-documented ratio, drifts to a "wrong" color like all-green or all-white to demonstrate poor growth).
- A water/nutrient gauge tied to the pillow (Veggie) vs. reservoir (PONDS) choice, and to Module 01's water-recycler rate as today.

**Optional stretch — 3D toggle**, following the exact "view toggle" pattern already proposed in `docs/solar-flare-simulator-proposal.md`: a Three.js chamber interior (LED panel, 6 pillow slots, plant meshes that scale/color with health) with the 2D view as the default/fallback. Only worth building if the 2D pass ships first and there's time left — do not block the module launch on this.

**Interaction flow (replaces "trigger crop failure → drag rationing sliders"), entirely client-side:**
1. `btn-trigger-crop-failure` → relabel to **"Simulate Veggie failure"** (or similar) — plants visibly start wilting/fungal in the chamber view, mirroring the Kelly zinnia incident, with the mission-log flavor text sourced from that real incident.
2. User picks a **diagnosis** (overwatering / airflow / light spectrum / nutrient) — right/wrong choices are checked against a small hand-written answer key grounded in the same NASA text (overwatering + poor airflow is the documented real cause), the same way Module 05's safe-zone check (`isInSafeZone()`) is a pure local function.
3. User adjusts **light spectrum** and **water delivery method** (pillow vs. PONDS reservoir) sliders/toggles — chamber visual updates live, same "recompute on every input change" pattern the current `recomputeSimMetrics()` uses, just without the network round trip.
4. **"Run simulation"** (kept) runs a local deterministic function — a direct client-side port of the old `computeSurvivalProbability()` shape, renamed to something like `computeCropRecovery()` — that takes the diagnosis correctness + light/water settings and returns a `crop_health_pct` (or `days_to_harvest`) plus hand-written outcome copy (correct diagnosis + good settings → full recovery text; wrong diagnosis → plants continue declining, same "try again" loop Module 05's retry button uses).
5. Successful recovery produces a harvest-yield number that can still feed the food-buffer language the console already uses elsewhere, so the module keeps a legible "how much food does this get us" payoff without a network call.

## Frontend changes (`frontend/mission-console.html`) — the only file this plan touches

- **Module head** (line ~851–854): update eyebrow copy — recommend `Module 03 · Interactive` to match Module 05's `Module 05 · Interactive` / Module 04's `Module 04 · Prototype` badge convention, now that this tab is no longer one of the RAG-grounded modules; title → `Growing Plants in Space`; description → something like "Simulates a Veggie grow-chamber failure and recovery, grounded in NASA's real plant-research findings — a hands-on module, not backed by the retrieval pipeline."
- **Add a Module-05-style disclaimer line** directly under the module head, reusing the `t5-proto-note` pattern verbatim in spirit: *"How to play — this module is a hands-on simulation, not backed by live telemetry or the retrieval pipeline the rest of this console uses."*
- **Tab comment banners**: update the `<!-- TAB 3 — SUPPLY CHAIN... -->` and `/* TAB 4 — SUPPLY CHAIN... */` header comments (lines 848, 3125) to match, and append `(self-contained)` the way Modules 05/06's banners already do.
- **Sim panel markup** (lines 859–912): replace the ration/days sliders and food-energy metrics with the diagnosis control, light-spectrum control, water-delivery toggle, and the new chamber SVG mount point (`food-chart-wrap` → e.g. `grow-chamber-wrap`).
- **JS block "Food chart + rationing simulator"** (lines ~3325–3489): delete the network-dependent parts; replace `nominalFoodCurve`, `unmitigatedCurve`, `rationedCurve`, `computeSurvivalProbability`, `drawFoodChart` with the chamber-rendering + local `computeCropRecovery()` functions described above. No `fetch()`/`API_BASE_URL` call remains in this block. Reuse the existing `lineChartSVG()` helper if a supplementary "yield over time" chart is still wanted alongside the chamber view.
- **`sideResources`/`buildWaterCard()`** (lines ~3169–3260): keep, retarget captions from "hydroponics failure" generic language to plant-specific language (e.g. "irrigation draw from active Veggie pillows").
- **`btnTriggerCrop`/`btnResetSupply` handlers** (lines ~3489–3545): relabel and rewire to the new diagnosis/recovery flow described above — all local state, no request/response handling to remove-and-replace.

## Assets / visual content needed

- Simple plant icon states (healthy / wilting / fungal) — inline SVG paths, consistent with the console's existing icon system (`sectorIcon()` etc.), no external image assets required.
- LED bar gradient (red/blue/magenta-pink) — CSS/SVG gradient, no asset needed.
- If the 3D stretch view is built: reuse the Three.js import map already present in `solar-cme-3d-simulator.html` rather than adding a new dependency.

## Build order

1. Write the small hand-authored fact/outcome table (diagnosis options, light-spectrum outcomes, water-delivery outcomes) from the NASA source material — this is the only "content" step and has no dependency on backend or ingestion work.
2. Build the 2D chamber SVG + diagnosis/light/water controls in `mission-console.html`, wired to `computeCropRecovery()` — a pure local function, unit-testable by hand in the browser console.
3. Update module head copy, disclaimer line, tab comments, and cross-link caption text (water card, spare-parts card).
4. Verify Module 01 (water recycler rate) and Module 02 (Kit A/B triage banner) integrations still function against the retitled tab.
5. Optional stretch: 3D chamber toggle.
6. Update `README.md`'s module walkthrough (item 4 in "How to Use," and the architecture paragraph's "a rationing plan" mention) and `docs/light-dark-mode-plan.md`'s module list, which both currently describe this tab as backend-grounded rationing.

## Verification checklist

- [ ] No `fetch()`/network call remains anywhere in the Module 03 tab's JS — confirms it's fully self-contained like Module 05/06.
- [ ] `backend/tests/test_rationing.py` still passes untouched (nothing in this plan modifies backend code).
- [ ] Chamber view visibly responds to every slider/toggle without needing "Run simulation" (matches the current live-preview UX).
- [ ] Wrong diagnosis choice produces a "still declining, try again" state; correct diagnosis + reasonable light/water settings produces a full-recovery state — mirrors Module 05's retry loop.
- [ ] Module 01 water-recycler degradation still visibly changes the water card on this tab.
- [ ] Module 02 Kit A/B triage step still decrements the medicine card and fires its cross-tab alert with correct copy.
- [ ] `README.md` and `docs/light-dark-mode-plan.md` no longer describe this tab as RAG-grounded rationing.
- [ ] Existing console visual design/theme is untouched, per `DEVELOPMENT.md`'s ground rule for IBM Bob-assisted changes.
