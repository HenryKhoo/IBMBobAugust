# Plan: Improve Module 03 — Growing Plants in Space (v2)

Reference sample reviewed: [farmable.tech](https://farmable.tech/) — a real farm-operations SaaS (block-level "digital twin" tracking, a spray/treatment journal, QR-coded harvest traceability lot codes, audit-ready compliance exports, AI-generated field insights). It's an Earth-agriculture compliance tool, not a spaceflight sim, so nothing here is copied wholesale — each idea below is translated into what's operationally true for a single vessel's Veggie/APH grow bay, and built with the console's existing constraints: single-file, client-side-only for this module, deterministic arithmetic (no randomness, no model calls), no new CSS tokens, existing component classes reused.

## Current state (per `docs/module-03-growing-plants-in-space-plan.md`, already shipped)

One hand-authored scenario: the documented Scott Kelly zinnia incident (overwatering + poor airflow → fungus). Four diagnosis choices (one correct, three plausible-wrong), a light-spectrum slider, a water-delivery toggle, a deterministic `computeCropRecovery()` score, a 6-slot SVG chamber view, and live coupling into the water/spare-parts resource cards plus the global incident log. The original plan's "bonus/stretch facts" (APH nutrient controls, BRIC-LED flag-22 immune-suppression experiment, VEG-03 transplant recovery, multi-crop picker, 3D toggle) were flagged but never built — that's most of the room to grow here.

## Improvements, translated from the Farmable reference

1. **In-module grow journal.** Every diagnosis/light/water change already fires `logIncident('T4', ...)` into the global incident log, but nothing surfaces inside the module itself. Add a small scrollable log panel under the sim output — Farmable's "the record builds itself while you work" idea — so a player can see the sequence of attempts that led to the fix, not just the final outcome. Pure UI, reads state that already exists; no new arithmetic.

2. **Harvest lot record on full recovery.** When `computeCropRecovery()` clears the recovery threshold (health ≥ 85), stamp a small record — crop, diagnosis path taken, final light/water settings, in-sim date — into a short in-module list. This is the direct analog of Farmable's QR harvest-lot traceability code, reframed as a crew food-safety record rather than an FDA compliance artifact. Feeds naturally into item 5 below.

3. **A second real documented failure mode.** Right now "wrong" diagnoses are red herrings with no scenario of their own. Add one more NASA-documented scenario as a second selectable trigger — the APH controlled-release-fertilizer/nutrient scenario is the best fit (it's already sourced in the original plan's fact list and gives the "nutrient deficiency" option in the current answer key an actual scenario to be correct about, instead of always being a decoy). Same pattern as the zinnia case: its own answer key, its own hand-written outcome copy, grounded in the same source material — not invented.

4. **Multi-unit chamber roster (stretch).** Model Veggie and APH as two independently-tracked grow units instead of one generic bay — Farmable's block-level tracking, translated to "which grow unit is this diagnosis for." Reuses the existing chamber SVG renderer parameterized per unit rather than building a second one. Higher effort than items 1–3; sequence it last given the Aug 30 deadline.

5. **Wire the outcome into the after-action report.** The console already generates an after-action report elsewhere; Module 03's outcome (recovered crop health %, spare-parts draw avoided, harvest lots logged) should feed it the way the old rationing sim did — Farmable's "audit-ready export, one click," translated to the console's existing report generator rather than a new export feature.

6. **One-line plain-language insight after "Run simulation."** A short deterministic sentence keyed off health tier + diagnosis path (not a model call — same hand-written-copy discipline the module already uses), in the same voice as Module 01's plain-language translator. Echoes Farmable's "AI-powered insights" card without adding real inference cost or breaking the "grounded, not guessed" rule.

7. **Crop picker reskin (stretch, cosmetic).** Let the player pick which documented crop is in the bay (lettuce, kale, dwarf wheat, zinnias, etc. — full list already in the original plan) purely to reskin chamber labels/copy. No new mechanics, lowest priority.

### Explicitly not translated

EPA/FSMA-style compliance records, weather-station integrations, payroll/timesheets, multi-farm enterprise portals — none of these have a counterpart in a single-vessel, single-crew mission console, and inventing one would break the "operationally truthful" principle the rest of the console holds to.

## Build order

1. In-module grow journal (item 1) — lowest risk, pure UI over existing state.
2. Harvest lot record (item 2) — small new state array, no new arithmetic.
3. Second failure scenario — APH nutrient case (item 3) — content + answer-key work, same shape as the existing one.
4. After-action report hook + one-line insight (items 5–6).
5. Stretch, only if time allows before Aug 30: multi-unit chamber roster (item 4), crop picker reskin (item 7), 3D toggle (already flagged as stretch in the original plan).

## Verification checklist

- [ ] No `fetch()`/network call introduced anywhere in Module 03 — stays fully self-contained.
- [ ] New APH scenario's answer key and outcome copy are traceable to the NASA source material already cited in the original plan, not invented.
- [ ] Grow journal and harvest-lot list clear correctly on "Reset."
- [ ] Existing Module 01 (water) / Module 02 (medicine kit) cross-tab couplings still fire unchanged.
- [ ] After-action report includes Module 03's outcome when a recovery has occurred, and omits it cleanly when the module was never triggered.
- [ ] No new CSS tokens/palette entries; all new UI reuses existing component classes.

## Open questions for Henry

- Priority call given the Aug 30 deadline: is items 1–3 (journal, harvest lot, second scenario) the right cutoff, with 4–7 as stretch only if time remains?
- Should the harvest-lot list persist across "Reset," or clear with everything else (current sim state clears fully on reset)?
- APH nutrient scenario as the second failure mode, or would BRIC-LED's flag-22 immune-suppression case be a better fit for the module's tone?
