# Preset Q&A — draft for review

Grounded Baseline-voice answers for the frontend's suggested "chip" questions, sourced strictly from `backend/data/chortlechat_corpus.json`. Nothing here is wired into code yet — this is the content-prep step before building the cache-first lookup.

**Count correction:** the frontend's `DOMAINS` array has **15 unique chip questions**, not 18 — "All" repeats 5 questions that also appear under their own domain, so there are only 15 distinct strings total. All 15 are covered below.

Each entry shows: the exact chip text, the drafted answer, the source citation, and a confidence note — **Strong** (passage directly answers the question), **Partial** (passage is on-topic but doesn't fully answer as asked, drafted answer says only what the source supports), or **No match** (nothing in the corpus actually answers this; flagged rather than fabricated).

---

### 1. What ocean heat conditions favor tropical cyclone intensification?
**Strong match.**

> A barrier layer thickness of 10-30 meters combined with a tropical cyclone heat potential of 40-80 kJ/cm² favors intensification in the central Bay of Bengal. As storm intensity increases, the right-rear sector of the cyclone shows the largest heat-potential anomalies, and sea-surface cooling beneath the strongest, slowest-moving storms reaches 0.5-1.2°C in the inner core.

Source: `science_reference:nasa-smd-50#chunk0`

---

### 2. How does eyewall mesovortex dynamics affect a hurricane's intensity?
**Partial match** — the source documents mesovortex structure and behavior, not a quantified link to intensity. Drafted to say only what it supports.

> In Hurricane Ike, mesovortices within the eyewall showed a consistent arrangement of vorticity and vertical-velocity maxima wherever they formed in the eyewall. Mesovortices kept forming even after the storm's center moved onto land, though their structure diverged from pre-landfall mesovortices as the storm interacted with the coastline and weakened. The source describes this structural behavior; it does not quantify how much eyewall mesovortices change peak intensity.

Source: `science_reference:nasa-smd-10#chunk0`

---

### 3. What atmospheric conditions influence tropical cyclone formation?
**No match.** Nothing in the corpus addresses genesis-favorable atmospheric conditions (wind shear, moisture, instability) directly — the closest passages cover ocean heat content's effect on *intensification* (already used for Q1) or the Saharan Air Layer's effect on *suppressing* activity (used for Q4). Recommend leaving this chip on live retrieval rather than forcing a mismatched preset answer.

---

### 4. How does airborne Saharan dust affect tropical cyclone development?
**Strong match.**

> The Saharan Air Layer tends to suppress Atlantic tropical cyclone activity by introducing dry, stable air into the storm, which increases vertical wind shear and the temperature inversion at lower levels. Separately, dust within the layer can act as cloud condensation and ice nuclei, influencing storm development by altering hydrometeor properties, diabatic heating distribution, and thermodynamic structure — as seen with Hurricane Erin in 2001. The relative size of these two effects, suppression versus microphysical influence, is still not fully resolved.

Source: `science_reference:nasa-smd-80#chunk0` (suppression mechanism), `science_reference:nasa-smd-90#chunk0` (CCN/microphysics mechanism)

---

### 5. What is the impact of Saharan dust on the atmosphere?
**Strong match.**

> An estimated 240 ± 80 million tons of Saharan dust cross the Atlantic from Africa every year. Dust directly affects Earth's radiative balance by absorbing and scattering sunlight, and dust coated with sulfur or other soluble material can also act as cloud condensation and ice nuclei, altering cloud development.

Source: `science_reference:nasa-smd-85#chunk0`, `science_reference:nasa-smd-86#chunk0`

---

### 6. How are dust storms characterized by particle size?
**Partial match** — the source characterizes dust by spectral reflectance signature (via MODIS bands), not by a particle-size distribution as literally asked.

> Dust storms are characterized using MODIS spectral reflectance rather than direct particle sizing: the reflectance of dust (sand and soil) increases with wavelength between 0.4 and 2.5 μm, reaching a minimum in MODIS band 3 and a maximum in band 7. This spectral signature is distinct enough from cloud reflectance to distinguish dust storms from clouds in satellite imagery.

Source: `science_reference:nasa-smd-25#chunk0`

---

### 7. How are historical droughts reconstructed from climate data?
**Strong match.**

> Historical drought reconstruction relies on precipitation records that must first be corrected for non-climatic biases — issues like snowfall-to-liquid conversion, rain gauge placement affecting collection in wind, evaporation loss between infrequent readings, and changes in instrumentation or the physical environment around a gauge. Because undercounting is worst in the cold season, this kind of reconstruction is often restricted to the warm season (April-August) and relies on careful screening of the best available records.

Source: `science_reference:nasa-smd-30#chunk0`

---

### 8. How is satellite-based precipitation data validated on the ground?
**Strong match.**

> Satellite precipitation estimates from GPM's radar and imager instruments are compared against quality-controlled ground observations — NPOL radar, high-resolution rain-rate radar, disdrometers, and rain gauges — accounting for a fall-delay time lag between the satellite overpass and when rain reaches the surface. That lag isn't constant; it varies between 0 and 30 minutes after overpass, so this study compared satellite retrievals against the ground-based mean measured 2-8 minutes after overpass time.

Source: `science_reference:nasa-smd-15#chunk0`

---

### 9. What evidence do scientists use to study climate change over time?
**Partial match** — reused from a water-quality case study rather than a general treatment of climate-change evidence, since the corpus has no passage framed at that general level.

> One example: researchers analyzed decades of time-series data on spring water quality and quantity using the Mann-Kendall trend test, a statistical method for detecting gradual trends in a long record. That analysis attributed decreasing spring discharge to declining precipitation (a climate-linked driver) and separately attributed water-quality deterioration to human activity such as mining, agriculture, and urbanization — illustrating how long-term monitoring records and trend tests are used together to separate a climate signal from other causes.

Source: `science_reference:nasa-smd-110#chunk0`, `science_reference:nasa-smd-111#chunk0`

---

### 10. What environmental factors drive wildland fire risk?
**Strong match.**

> Wildland fires are a major source of fine particulate pollution in the US, accounting for roughly 25% of primary PM2.5 emissions. Ignition sources differ by region — human-ignited prescribed and agricultural burns dominate in the southeastern US, while about 70% of burned area in the western US comes from lightning-ignited fires — and in both regions, burned area is closely tied to environmental conditions and can be affected by a changing climate.

Source: `science_reference:nasa-smd-35#chunk0`

---

### 11. What causes environmental degradation?
**Strong match.**

> Pollution is the main driver of environmental degradation. It comes from a variety of sources, including vehicle emissions, agricultural runoff, accidental chemical release from factories, and poorly managed harvesting of natural resources — and its effects include depleting resources, disturbing ecosystems, and contributing to the loss of animal populations.

Source: `science_reference:nasa-smd-0#chunk0`, `science_reference:nasa-smd-66#chunk0`

---

### 12. How does pollution affect water quality?
**Strong match.**

> In a study of karst spring water in China, anthropogenic activity — coal mining and quarrying, agriculture, and urbanization — was found responsible for measurable water-quality deterioration over time, tracked using the Mann-Kendall trend test on decades of monitoring data. Separately, declining precipitation linked to climate change reduced spring discharge itself, showing that water quantity and quality respond to different but overlapping pressures.

Source: `science_reference:nasa-smd-110#chunk0`, `science_reference:nasa-smd-112#chunk0`

---

### 13. What causes severe mesoscale thunderstorm systems?
**Partial match** — the source characterizes high-shear, low-CAPE (HSLC) severe convection regionally rather than stating a general causal mechanism.

> One recognized category, high-shear, low-CAPE (HSLC) severe convection, remains hard to forecast and is responsible for most significant tornado and wind reports during the cool season, especially overnight — a period when typical severe-weather indicators are otherwise unfavorable. Its regional character differs: western US HSLC events tend to involve a drier lower troposphere and a surface triple point or upslope setup, while eastern events are more associated with low cloud bases along a warm sector or cold front, even though the broader upper-atmosphere forcing looks similar across regions.

Source: `science_reference:nasa-smd-5#chunk0`

---

### 14. What is a dryline and how does it trigger severe weather?
**Strong match.**

> A dryline is a boundary separating a region of very dry air from one with much higher moisture content. Drylines matter because they act as a trigger for thunderstorms, which can produce severe weather — in subtropical southern Africa, they're most frequent over eastern South Africa in early summer, exactly when large-hail and damaging-wind storms are most likely.

Source: `science_reference:nasa-smd-130#chunk0`

---

### 15. What is cold-air damming?
**Partial match** — the source is a specific case study (a March 22 synoptic event) rather than a textbook definition; the drafted answer describes the phenomenon through that case, as a grounded system would.

> The source documents a cold-air damming case where a surface anticyclone stayed nearly stationary while a low-pressure system tracked east of Jackson, Mississippi, strengthening the pressure gradient in the mountain-parallel direction along the Appalachians. That setup showed increased ridging east of the mountain crests (Virginia to Georgia) and increased troughing over and west of the Appalachians (New York to Tennessee) — the characteristic pattern of cold, dense air banking up against the eastern slopes.

Source: `science_reference:nasa-smd-125#chunk0`

---

## Summary of flags

- **15 questions total, not 18** — worth confirming with you before this goes further.
- **1 with no usable source** (#3, TC formation conditions) — recommend leaving it on live RAG rather than forcing a mismatched preset.
- **5 partial matches** (#2, #6, #9, #13, #15) where the drafted answer stays honest about what the source does and doesn't establish, rather than overclaiming to sound more complete.
- Everything above is still watsonx/Gemini-free content prep — no JSON lookup file or `ask_chortlechat` changes yet, per your "pre-prepared first."
