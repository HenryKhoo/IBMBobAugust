# Proposal: Interactive Solar Flare Simulator

## Concept

An interactive 3D (with a 2D fallback) scene showing the Sun, Earth, and a spacecraft. The user triggers solar flares of five different strengths and watches the physical consequences play out on the spacecraft and on Earth in real time. This extends the existing `solar-cme-3d-simulator.html` prototype (Three.js, Sun/Earth/orbiting probe already built) rather than starting from scratch, and fits the North Star console's "Reimagine Space Exploration with AI" theme by making an abstract hazard — space weather — tangible and actionable.

## Scene

- **Sun**: rendered bright red/orange (`#ff2d1f` core with an animated flare-orange corona), pulsing point light, slow rotation. Flare events erupt as an animated arc of particles/plasma shooting off the surface.
- **Earth**: orbiting at a fixed radius, with a visible magnetosphere shell that visibly compresses or lights up (aurora ring) when a flare hits.
- **Spacecraft**: positioned between Sun and Earth (or in transit, using the existing probe-launch mechanic), with a shield/health indicator that can take damage from a flare.
- **View toggle**: a button to switch between the 3D orbit-camera view and a simplified 2D top-down "orbit diagram" view (Sun — flare arc — spacecraft — Earth on a line/ellipse), useful for smaller screens or a quicker read of what's happening.

## The five flare classes

A simple selector (or a "surprise me" random button) lets the user pick a class and fire it:

| Class | Relative strength | Color cue | Spacecraft impact | Earth impact |
|---|---|---|---|---|
| A | Weakest (baseline, ~background level) | pale yellow | none | none |
| B | 10x A | yellow | minor sensor noise | none noticeable |
| C | 10x B (moderate, most common) | orange | brief instrument glitch, auto-recovers | none noticeable |
| M | 10x C (strong) | red-orange | radiation warning, spacecraft auto-safes non-critical systems | possible minor radio blackout at poles |
| X | 10x M (most powerful; can be sub-graded like X1, X2 … the largest on record was ~X45) | bright white-red flash | shields flare, systems reboot required, GPS/comm loss risk | radio blackouts, possible grid stress, visible aurora expansion |

Each class fires a visibly bigger/faster particle burst from the Sun, and the impact readout (a small HUD panel) explains in plain language what just happened to the spacecraft and to Earth — this is the "teaching moment" of the simulator.

## Interactivity

- Click/select a flare class → animated eruption travels from Sun toward spacecraft/Earth → impact effects trigger (screen flash, shield-meter drop, "signal lost" banner, aurora glow) → HUD explains the effect and, for M/X class, what real-world protections exist.
- A "protect the mission" toggle lets the user pre-emptively shield the spacecraft (put it in safe mode) before firing a flare, showing the before/after damage difference — this demonstrates the "can we protect ourselves" angle directly rather than just narrating it.
- Optional: a running mission log ("C3.2 flare detected — no action needed", "X1.4 flare detected — spacecraft entering safe mode") so the simulator doubles as a plain-language space-weather feed, consistent with the North Star console's grounded, plain-language style.

## Protection layer (tie-in content)

Surface this as a short info panel unlocked after the first M or X class flare, covering the four real-world mitigation strategies: early warning (space-weather radar/satellites), shielding + safe-mode for satellites and grid hardening, backup systems for GPS/comms, and public education. This keeps the fun simulation grounded in the real strategy: we can't stop flares, but early warning, shielding, backups, and awareness limit the damage.

## Build approach

1. Fork/extend `solar-cme-3d-simulator.html`: recolor the Sun, add a flare-class selector UI, add particle-burst animation from Sun toward target.
2. Add impact logic: a lookup table (the five-class table above) driving shield-meter damage, screen effects, and HUD text.
3. Add the 2D view as an alternate render mode (simple SVG/canvas top-down diagram) toggled by one button, reusing the same state/impact logic.
4. Add the protection info panel and mission log.
5. Polish pass: sound/flash cues, mobile layout check, and a "reset" button.

## Why it fits

It turns a static fact sheet (flare classes, mitigation strategies) into something a user experiments with and remembers, reuses the project's existing 3D prototype instead of duplicating effort, and matches the console's philosophy of turning raw signals into a clear, grounded, actionable read.
