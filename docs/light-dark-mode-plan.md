# Light/Dark Mode Plan: Mission Console

Status: **implemented** in `frontend/mission-console.html` (Aug 19). Tasks
1–6 below are done; task 7 (full visual sweep for anything theme-unaware)
is worth a manual pass but nothing was found in the color audit. The
palette values in §3 were used as-is rather than hand-tuned.

## 1. Decision

Add a user-facing theme toggle to `frontend/mission-console.html`, with two
themes (light, dark) and **light as the default** on first visit. Persist the
user's choice across reloads. No third theme, no auto-follow-OS mode unless
noted as an open decision below.

## 2. Current state

The console is a single HTML file (3,971 lines) with all color values
centralized as CSS custom properties in one `:root` block (lines 11–26):
`--bg`, `--panel`, `--panel-2`, `--panel-3`, `--line`, `--line-strong`,
`--ink`, `--ink-dim`, `--ink-faint`, `--invert-bg`, `--invert-ink`. Nearly
every CSS rule in the file references these tokens rather than hardcoding
colors — good news, this is most of the work already done.

Three places don't use CSS variables, because they're JS-driven canvas/WebGL
drawing, which can't read custom properties directly:

| Location | Line | What it does |
|---|---|---|
| `EKG_INK` constant | 1518 | `'#ececee'` — canvas `strokeStyle` for the EKG waveform (triage module) |
| `radialGauge` fill default | 1185 | `ctx.fillStyle = color \|\| '#ececee'` — canvas gauge default color |
| `COLOR` object | 1057 | `{ dim:0x5a5a62, mid:0xa2a2a9, bright:0xececee, breach:0xff3b30 }` — three.js schematic materials |

All three currently hardcode the *dark*-theme ink value. They'll need to
track the active theme instead of a fixed literal.

One more wrinkle: `--invert-bg`/`--invert-ink` are used for the "critical"
status pill (`.status-pill.level-critical`, line 99) — it inverts to
light-bg/dark-ink to read as an alarm against the dark console. In a light
theme, inverting the same way would mean dark-bg/light-ink, which is a
different (but still valid) alarm treatment — see §5.

## 3. Token restructure

Today `:root` holds one (dark) palette. Restructure so `:root` holds the
**light** (default) palette, and a `[data-theme="dark"]` selector on `<html>`
overrides with the current dark values:

```
:root { /* light palette — new values, default */ }
html[data-theme="dark"] { /* current dark palette, unchanged */ }
```

This means the toggle only ever needs to set/remove one attribute
(`data-theme="dark"` on `<html>`); no JS needs to touch individual tokens.

Light palette values need to be chosen — this is a design decision, not a
mechanical port. Suggested direction, staying in the console's existing
near-monochrome / high-contrast style rather than introducing color:

| Token | Dark (current) | Light (proposed) |
|---|---|---|
| `--bg` | `#0b0b0c` | `#f5f5f4` |
| `--panel` | `#141416` | `#ffffff` |
| `--panel-2` | `#1a1a1d` | `#ececea` |
| `--panel-3` | `#0f0f10` | `#eeeeec` |
| `--line` | `#2a2a2e` | `#d8d8d5` |
| `--line-strong` | `#5a5a62` | `#9a9a96` |
| `--ink` | `#ececee` | `#141414` |
| `--ink-dim` | `#a2a2a9` | `#4a4a48` |
| `--ink-faint` | `#6c6c73` | `#767672` |
| `--invert-bg` | `#ececee` | `#141414` |
| `--invert-ink` | `#0b0b0c` | `#f5f5f4` |

Treat these as a starting point to eyeball and adjust — the goal is
inverted-but-equivalent contrast (roughly matching WCAG AA text contrast
ratios against `--panel`), not exact color math.

## 4. JS color sync

The three JS locations from §2 need a single source of truth that both CSS
and JS read, instead of JS having its own hardcoded literal. Approach:

- Add a small helper, e.g. `getThemeColors()`, that reads the resolved CSS
  custom property values off `document.documentElement` (via
  `getComputedStyle`) for whichever tokens the canvas/three.js code needs
  (`--ink`, `--line-strong`, `--ink-dim`, plus a fixed alarm red that stays
  constant in both themes, e.g. `#ff3b30`).
- Call it once at boot to set `EKG_INK` and the gauge default, and again
  inside the toggle handler so a live theme switch updates them.
- For the three.js `COLOR` object: same idea, but also needs
  `material.color.set(...)` calls on each affected mesh after toggling,
  since three.js materials don't re-read on their own. The schematic's
  `animate()` loop already runs continuously, so this only needs a
  one-time re-set at toggle time, not a per-frame read.
- The `breach` color (`0xff3b30` / `#ff3b30`) is an alarm red, not a theme
  token — keep it a fixed literal in both palettes rather than tying it to
  `--ink`.

## 5. Invert-pair decision for the critical status pill

Since `--invert-bg`/`--invert-ink` are already proposed to flip per-theme in
§3 (dark→light-on-dark stays as today, light→dark-on-light), the "critical"
pill will render as a solid dark block in light mode and a solid light block
in dark mode. Both read as "inverted from the surrounding UI," which
preserves the existing visual language (critical = invert) without a special
case. No extra work beyond the token values themselves.

## 6. Toggle control

- **Placement**: top bar, in the `.status-cluster` next to the MET clock and
  status pill (line ~82) — it's persistent chrome, visible regardless of
  which module tab is active.
- **Control type**: a small icon button (sun/moon), `aria-pressed` reflecting
  state, `aria-label="Toggle light/dark theme"`. Matches the console's
  existing terse, icon-and-label instrument-panel style rather than a
  labeled switch.
- **Behavior**: click flips `data-theme` on `<html>`, re-syncs the three JS
  color spots (§4), writes the choice to `localStorage`.

## 7. Persistence and default

- `localStorage` key, e.g. `console-theme`, value `"light"` or `"dark"`.
- On load: if no stored value, default to **light** (per requirement) and do
  not consult `prefers-color-scheme` — see open decision below if that's
  worth reconsidering.
- To avoid a flash of dark-then-light (or vice versa) on load, the
  theme-resolving script needs to run inline in `<head>`, before first
  paint, and before the big `<style>` block's variables are used — not
  deferred to the bottom of `<body>` where the rest of the app JS currently
  lives.

## 8. Task breakdown

| # | Task | Notes |
|---|---|---|
| 1 | Add light palette to `:root`, move current values into `html[data-theme="dark"]` | §3 |
| 2 | Inline head script: read `localStorage`, default `"light"`, set `data-theme` before paint | §7 |
| 3 | Toggle button markup + placement in topbar | §6 |
| 4 | Toggle click handler: flip attribute, write `localStorage`, call color-resync | §6 |
| 5 | `getThemeColors()` helper + resync calls for `EKG_INK`, gauge default, three.js `COLOR` | §4 |
| 6 | Adjust `--invert-bg`/`--invert-ink` light values, spot-check the critical pill in both themes | §5 |
| 7 | Pass over every module's panel content in light mode for anything that assumed dark (e.g. image/icon assets with baked-in dark backgrounds, if any) | new — needs a visual sweep, not found in the token/color audit above |

## 9. Verification plan

- Toggle back and forth several times; confirm no flash/flicker, no
  console errors.
- Reload in each state; confirm the stored theme is what re-appears (no
  flash of the other theme first).
- Check contrast: `--ink` on `--panel`, `--ink-dim` on `--panel`, in both
  themes — rough WCAG AA pass (4.5:1 body text).
- Walk all five modules (crisis, telemetry, triage, rationing, space
  weather/ISS) in both themes: EKG canvas draws in the right ink color,
  three.js schematic materials update on toggle, gauges/sparklines/charts
  render correctly, the critical status pill is legible in both themes.
- Confirm `localStorage` isn't written until the user actually toggles
  (first-visit default stays light without polluting storage), or decide
  explicitly to write the default on first load — pick one and be
  consistent.

## 10. Open decisions

- **Respect `prefers-color-scheme` OS setting on first visit, or always
  default light regardless of OS?** Current instruction is "default light
  mode," read here as: ignore OS preference, always light until the user
  toggles. Flag if that's not the intent.
- **Toggle icon vs. labeled switch vs. text button** — icon-only fits the
  console's dense instrument-panel aesthetic but is less discoverable;
  a small text label (`"LIGHT" / "DARK"` in the existing mono/eyebrow style)
  may fit better given the rest of the UI leans on explicit mono labels
  over icons.
- **Scope of the light palette** — the table in §3 is a first pass; wants a
  visual pass against actual panel content (charts, gauges, the 3D
  schematic background) before treating it as final, since some SVG/canvas
  elements may need their own light-mode contrast check beyond the three
  JS spots already identified.

## 11. Relationship to the Vite migration plan

`docs/frontend-vite-migration-plan.md` (separate, also plan-only) proposes
splitting this same file into `styles/tokens.css` + `shared/` JS modules.
If both land, this theming work maps directly: the light/dark token split
becomes `tokens.css`, and `getThemeColors()` becomes a
`shared/theme.js` module. Doing the theme work first, on the single file, is
lower-risk than doing it mid-migration — recommend sequencing theme-toggle
before the Vite split if both are in scope, since it's the smaller, faster
change.
