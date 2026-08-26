# Preset Q&A — draft for review

Grounded Baseline- and Banter-voice answers for the frontend's suggested "chip" questions, sourced strictly from `backend/data/cosmos_corpus.json`.

**Status: wired, as a demo cache-first path, for both personas.** `app.services.cosmos` loads `backend/data/preset_qa.json` into a cache keyed by exact question text and, on a hit, answers straight from `baseline_answer` or `banter_answer` — whichever the request's persona asked for — with no retrieval call, no confidence-threshold gate, and no generation call for either persona. All 15 questions are covered, including the one the corpus doesn't actually answer (see #3 below), so a demo run never depends on a live vector store or instruct model for any suggested chip. `confidence` stays `None` on every cache-hit response (same meaning it already carries for "nothing was retrieved," which is literally true here). See `backend/tests/test_cosmos.py`'s "Preset chip-question cache" section for the covering tests.

**Count correction:** the frontend's `DOMAINS` array has **15 unique chip questions**, not 18 — "All" repeats 5 questions that also appear under their own domain, so there are only 15 distinct strings total. All 15 are covered below.

Each entry shows: the exact chip text, the drafted Baseline answer, the drafted Banter restyle (hand-written under the same "no new fact" rule `_BANTER_PROMPT` enforces live — personality may differ, the underlying claims must not), the source citation, and a confidence note — **Strong** (passage directly answers the question), **Partial** (passage is on-topic but doesn't fully answer as asked, drafted answer says only what the source supports), or **No match** (nothing in the corpus actually answers this; flagged rather than fabricated).

Every Banter answer opens with an actual short joke — a setup/punchline one-liner or pun on that entry's topic, in the spirit of the [Short Jokes dataset](https://www.kaggle.com/datasets/abhinavmoudgil95/short-jokes/) (a Kaggle collection of 200k+ short jokes for humor research) — before restating the same facts Baseline gives. The joke itself is original, written for this content, not pulled from that dataset.

---

### 1. What ocean heat conditions favor tropical cyclone intensification?
**Strong match.**

Baseline:
> A barrier layer thickness of 10-30 meters combined with a tropical cyclone heat potential of 40-80 kJ/cm² favors intensification in the central Bay of Bengal. As storm intensity increases, the right-rear sector of the cyclone shows the largest heat-potential anomalies, and sea-surface cooling beneath the strongest, slowest-moving storms reaches 0.5-1.2°C in the inner core.

Banter:
> Why did the tropical cyclone break up with the shallow water? It needed something with more depth. Picture the ocean as a fuel tank: a 10-30 meter buffer layer sitting on top of 40-80 kJ/cm² of stored heat is basically premium unleaded for a storm over the central Bay of Bengal. And as the cyclone spins up, it doesn't sip evenly — the right-rear side drains the tank hardest, cooling the sea surface there by 0.5-1.2°C right under the strongest, slowest-crawling storms.

Source: `science_reference:nasa-smd-50#chunk0`

---

### 2. How does eyewall mesovortex dynamics affect a hurricane's intensity?
**Partial match** — the source documents mesovortex structure and behavior, not a quantified link to intensity. Drafted to say only what it supports.

Baseline:
> In Hurricane Ike, mesovortices within the eyewall showed a consistent arrangement of vorticity and vertical-velocity maxima wherever they formed in the eyewall. Mesovortices kept forming even after the storm's center moved onto land, though their structure diverged from pre-landfall mesovortices as the storm interacted with the coastline and weakened. The source describes this structural behavior; it does not quantify how much eyewall mesovortices change peak intensity.

Banter:
> What do you call a hurricane's eyewall doing the same dance move over and over? A mesovortex — it just can't stop repeating its best routine. In Hurricane Ike, mesovortices within the eyewall showed a consistent arrangement of vorticity and vertical-velocity maxima wherever they formed. The show didn't even stop at landfall; mesovortices kept forming, just with a slightly different routine once the coastline started interfering. What I can't tell you is how many points that performance added to Ike's peak intensity — the source never keeps that scoreboard.

Source: `science_reference:nasa-smd-10#chunk0`

---

### 3. What atmospheric conditions influence tropical cyclone formation?
**No match.** Nothing in the corpus addresses genesis-favorable atmospheric conditions (wind shear, moisture, instability) directly — the closest passages cover ocean heat content's effect on *intensification* (already used for Q1) or the Saharan Air Layer's effect on *suppressing* activity (used for Q4). This chip is cached too (`grounded: false`, `baseline_answer`/`banter_answer` both `null`) — a hit routes straight to `_fallback_response`, the same honest "no grounded answer" text every other unanswerable question gets, still without touching retrieval or the model. Preset here means "preset to say I don't know," never a fabricated answer.

---

### 4. How does airborne Saharan dust affect tropical cyclone development?
**Strong match.**

Baseline:
> The Saharan Air Layer tends to suppress Atlantic tropical cyclone activity by introducing dry, stable air into the storm, which increases vertical wind shear and the temperature inversion at lower levels. Separately, dust within the layer can act as cloud condensation and ice nuclei, influencing storm development by altering hydrometeor properties, diabatic heating distribution, and thermodynamic structure — as seen with Hurricane Erin in 2001. The relative size of these two effects, suppression versus microphysical influence, is still not fully resolved.

Banter:
> Why did the hurricane avoid the Saharan Air Layer? It heard the air there had a dry sense of humor. The Saharan Air Layer plays bad cop to Atlantic hurricanes: it dumps in dry, stable air that cranks up wind shear and slaps a temperature inversion on the storm, mostly telling it to calm down. But that same layer carries dust that can act as cloud condensation and ice nuclei — tinkering with cloud particles, heating patterns, and the storm's structure, the way it did with Hurricane Erin back in 2001. Scientists still argue over which effect wins, the suppression or the dust tinkering — no verdict yet.

Source: `science_reference:nasa-smd-80#chunk0` (suppression mechanism), `science_reference:nasa-smd-90#chunk0` (CCN/microphysics mechanism)

---

### 5. What is the impact of Saharan dust on the atmosphere?
**Strong match.**

Baseline:
> An estimated 240 ± 80 million tons of Saharan dust cross the Atlantic from Africa every year. Dust directly affects Earth's radiative balance by absorbing and scattering sunlight, and dust coated with sulfur or other soluble material can also act as cloud condensation and ice nuclei, altering cloud development.

Banter:
> What do you call 240 million tons of dust taking an annual trip across the Atlantic? A really long commute with no frequent-flyer miles. Every year, roughly 240 million tons (give or take 80 million) of Saharan dust crosses the entire Atlantic. Once it's airborne, it messes with Earth's light budget by absorbing and scattering sunlight, and if it's picked up a sulfur coating along the way, it can even moonlight as a cloud condensation or ice nucleus, nudging how clouds form.

Source: `science_reference:nasa-smd-85#chunk0`, `science_reference:nasa-smd-86#chunk0`

---

### 6. How are dust storms characterized by particle size?
**Partial match** — the source characterizes dust by spectral reflectance signature (via MODIS bands), not by a particle-size distribution as literally asked.

Baseline:
> Dust storms are characterized using MODIS spectral reflectance rather than direct particle sizing: the reflectance of dust (sand and soil) increases with wavelength between 0.4 and 2.5 μm, reaching a minimum in MODIS band 3 and a maximum in band 7. This spectral signature is distinct enough from cloud reflectance to distinguish dust storms from clouds in satellite imagery.

Banter:
> How do scientists measure a dust storm without ever touching a single grain of sand? Very carefully — with a satellite instead of a magnifying glass. MODIS reads dust by its light signature: reflectance climbs as wavelength increases from 0.4 to 2.5 μm, bottoming out at band 3 and peaking at band 7. That fingerprint looks different enough from clouds that satellites can tell "dust storm" from "just a cloud" without anyone measuring particle sizes at all.

Source: `science_reference:nasa-smd-25#chunk0`

---

### 7. How are historical droughts reconstructed from climate data?
**Strong match.**

Baseline:
> Historical drought reconstruction relies on precipitation records that must first be corrected for non-climatic biases — issues like snowfall-to-liquid conversion, rain gauge placement affecting collection in wind, evaporation loss between infrequent readings, and changes in instrumentation or the physical environment around a gauge. Because undercounting is worst in the cold season, this kind of reconstruction is often restricted to the warm season (April-August) and relies on careful screening of the best available records.

Banter:
> Why can't you trust an old rain gauge's story? It always exaggerates — snow melts wrong, wind blows the rain away, and it forgets readings for days at a time. All of that baggage — snowfall-to-liquid conversion, wind-blown collection errors, evaporation between readings, decades of swapped-out instruments — has to be scrubbed out before a drought record means anything. And because winter is where gauges lie the most, reconstructions usually stick to the April-through-August stretch and cherry-pick only the most trustworthy records.

Source: `science_reference:nasa-smd-30#chunk0`

---

### 8. How is satellite-based precipitation data validated on the ground?
**Strong match.**

Baseline:
> Satellite precipitation estimates from GPM's radar and imager instruments are compared against quality-controlled ground observations — NPOL radar, high-resolution rain-rate radar, disdrometers, and rain gauges — accounting for a fall-delay time lag between the satellite overpass and when rain reaches the surface. That lag isn't constant; it varies between 0 and 30 minutes after overpass, so this study compared satellite retrievals against the ground-based mean measured 2-8 minutes after overpass time.

Banter:
> Why does rain get graded on a curve? Because it can take up to 30 minutes just to show up for class after the satellite already marked attendance. GPM's radar and imager readings get checked against ground truth: NPOL radar, high-res rain radar, disdrometers, and plain old rain gauges. Since that overpass-to-surface lag varies between 0 and 30 minutes, this study graded the satellite against the ground average measured 2-8 minutes post-overpass, not an instant snapshot.

Source: `science_reference:nasa-smd-15#chunk0`

---

### 9. What evidence do scientists use to study climate change over time?
**Partial match** — reused from a water-quality case study rather than a general treatment of climate-change evidence, since the corpus has no passage framed at that general level.

Baseline:
> One example: researchers analyzed decades of time-series data on spring water quality and quantity using the Mann-Kendall trend test, a statistical method for detecting gradual trends in a long record. That analysis attributed decreasing spring discharge to declining precipitation (a climate-linked driver) and separately attributed water-quality deterioration to human activity such as mining, agriculture, and urbanization — illustrating how long-term monitoring records and trend tests are used together to separate a climate signal from other causes.

Banter:
> What do climate scientists and detectives have in common? Both need a trend they can trust before they name a suspect. One case in point: decades of spring-water records run through the Mann-Kendall trend test — a tool built for spotting slow-motion trends — pinned shrinking spring flow on falling precipitation, a climate fingerprint, while pinning the water getting dirtier on human activity like mining, farming, and urbanization. Long records plus the right statistical test, and you can tell the climate's handwriting apart from everyone else's.

Source: `science_reference:nasa-smd-110#chunk0`, `science_reference:nasa-smd-111#chunk0`

---

### 10. What environmental factors drive wildland fire risk?
**Strong match.**

Baseline:
> Wildland fires are a major source of fine particulate pollution in the US, accounting for roughly 25% of primary PM2.5 emissions. Ignition sources differ by region — human-ignited prescribed and agricultural burns dominate in the southeastern US, while about 70% of burned area in the western US comes from lightning-ignited fires — and in both regions, burned area is closely tied to environmental conditions and can be affected by a changing climate.

Banter:
> Who starts most wildfires? Depends who you ask — the Southeast blames people, the West blames the sky, and the smoke doesn't care whose fault it is. Wildfires are responsible for about a quarter of the US's fine particulate (PM2.5) emissions. The Southeast mostly sees human-ignited prescribed and agricultural burns, while about 70% of the West's burned area starts with lightning. Either way, how much actually burns tracks environmental conditions, and a changing climate can shift that.

Source: `science_reference:nasa-smd-35#chunk0`

---

### 11. What causes environmental degradation?
**Strong match.**

Baseline:
> Pollution is the main driver of environmental degradation. It comes from a variety of sources, including vehicle emissions, agricultural runoff, accidental chemical release from factories, and poorly managed harvesting of natural resources — and its effects include depleting resources, disturbing ecosystems, and contributing to the loss of animal populations.

Banter:
> If Mother Nature filed a police report on environmental degradation, there'd only be one name on the suspect list: pollution — it's got alibis everywhere from tailpipes to factories. It shows up as vehicle emissions, agricultural runoff, the occasional factory chemical release, and resources harvested with more enthusiasm than planning. The damage isn't subtle either: depleted resources, disturbed ecosystems, and animal populations paying the price.

Source: `science_reference:nasa-smd-0#chunk0`, `science_reference:nasa-smd-66#chunk0`

---

### 12. How does pollution affect water quality?
**Strong match.**

Baseline:
> In a study of karst spring water in China, anthropogenic activity — coal mining and quarrying, agriculture, and urbanization — was found responsible for measurable water-quality deterioration over time, tracked using the Mann-Kendall trend test on decades of monitoring data. Separately, declining precipitation linked to climate change reduced spring discharge itself, showing that water quantity and quality respond to different but overlapping pressures.

Banter:
> How do you know a spring in China has had a rough few decades? Ask the Mann-Kendall trend test — it's basically the spring's unofficial therapist. Coal mining, quarrying, farming, and sprawling cities all left their mark on the water quality of a karst spring, measurably worse over time according to that trend test on decades of monitoring data. Meanwhile, a separate culprit, climate-linked drops in rainfall, was quietly shrinking how much water came out of the spring at all — proof that water's quantity and its quality don't always answer to the same cause.

Source: `science_reference:nasa-smd-110#chunk0`, `science_reference:nasa-smd-112#chunk0`

---

### 13. What causes severe mesoscale thunderstorm systems?
**Partial match** — the source characterizes high-shear, low-CAPE (HSLC) severe convection regionally rather than stating a general causal mechanism.

Baseline:
> One recognized category, high-shear, low-CAPE (HSLC) severe convection, remains hard to forecast and is responsible for most significant tornado and wind reports during the cool season, especially overnight — a period when typical severe-weather indicators are otherwise unfavorable. Its regional character differs: western US HSLC events tend to involve a drier lower troposphere and a surface triple point or upslope setup, while eastern events are more associated with low cloud bases along a warm sector or cold front, even though the broader upper-atmosphere forcing looks similar across regions.

Banter:
> What do you call severe weather that only strikes when everyone's asleep and the alarms are off duty? High-shear, low-CAPE (HSLC) convection — the ninja of thunderstorms. It's behind most of the significant cool-season tornado and wind reports, often overnight, exactly when the usual warning signs go quiet. And it doesn't even show up the same way twice: out West it favors a drier lower atmosphere with a surface triple point or upslope setup, while back East it prefers low clouds riding along a warm front or cold front — even though the atmosphere upstairs looks about the same either way.

Source: `science_reference:nasa-smd-5#chunk0`

---

### 14. What is a dryline and how does it trigger severe weather?
**Strong match.**

Baseline:
> A dryline is a boundary separating a region of very dry air from one with much higher moisture content. Drylines matter because they act as a trigger for thunderstorms, which can produce severe weather — in subtropical southern Africa, they're most frequent over eastern South Africa in early summer, exactly when large-hail and damaging-wind storms are most likely.

Banter:
> What's the driest breakup in nature? A dryline — bone-dry air splitting from its much muggier neighbor, and thunderstorms show up just to watch. That boundary is a thunderstorm's favorite trigger, and in subtropical southern Africa it shows up most over eastern South Africa in early summer, which just happens to be prime time for large hail and damaging winds.

Source: `science_reference:nasa-smd-130#chunk0`

---

### 15. What is cold-air damming?
**Partial match** — the source is a specific case study (a March 22 synoptic event) rather than a textbook definition; the drafted answer describes the phenomenon through that case, as a grounded system would.

Baseline:
> The source documents a cold-air damming case where a surface anticyclone stayed nearly stationary while a low-pressure system tracked east of Jackson, Mississippi, strengthening the pressure gradient in the mountain-parallel direction along the Appalachians. That setup showed increased ridging east of the mountain crests (Virginia to Georgia) and increased troughing over and west of the Appalachians (New York to Tennessee) — the characteristic pattern of cold, dense air banking up against the eastern slopes.

Banter:
> What do you call cold air stuck against the Appalachians with nowhere to go? A traffic jam that never got the memo to merge. In one case study, a surface high pressure system parked itself and stayed put while a low pressure system slid east of Jackson, Mississippi, cranking up the pressure gradient running alongside the Appalachians. The result looked exactly like the textbook picture — more ridging east of the mountains from Virginia to Georgia, more troughing on and west of them from New York to Tennessee.

Source: `science_reference:nasa-smd-125#chunk0`

---

## Summary of flags

- **15 questions total, not 18.**
- **1 with no usable source** (#3, TC formation conditions) — now cached to the honest fallback rather than left on live retrieval, so it never depends on a live vector store either.
- **5 partial matches** (#2, #6, #9, #13, #15) where the drafted answer stays honest about what the source does and doesn't establish, rather than overclaiming to sound more complete. Every Banter restyle inherits the same honesty — it never adds a claim Baseline's version didn't already make.
- **Every Banter answer now opens with an actual joke** (a one-liner or pun on the question's topic), not just a witty aside — see the intro note above.
- Wired into `ask_cosmos` for both personas (see Status note above) — this is no longer just content prep.
