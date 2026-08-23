# Plan: Persistent side-panel for chat sessions

Status: **Proposed — not yet built.** This is a plan for review before any
code changes to `frontend/app.html`.

## What's being asked for

A collapsible sidebar next to the main chat window, listing past and active
conversations with timestamps, rename, and delete. The main area keeps
showing the active message thread. On small screens the sidebar hides
behind a menu button.

## What already exists (don't rebuild this)

`frontend/app.html` already has a device-local conversation index —
`STORAGE_KEY_CONVERSATIONS` (`talkback:conversations`) in `localStorage`,
capped at `MAX_STORED_CONVERSATIONS = 20`. Each entry is
`{ sessionId, startedAt, title, persona }`, where `title` is auto-derived
from the first question asked (truncated to 80 chars). This index already
has: timestamps (`startedAt`, formatted via `formatConversationTimestamp`),
delete (`removeStoredConversation`, per-row `×` button plus a "Clear all"),
and open/resume (`openPastConversation`, which re-fetches the transcript
from `GET /conversation/history`).

It's surfaced today as `#pastConvPanel` — a modal-style overlay panel
(`.history-panel`, `hidden` by default) toggled by the "Past conversations"
button in the controls row, sitting alongside a second, separate modal
(`#historyPanel`, "Conversation history") that shows the *current* session's
turns read-only. Layout is a single centered column, `max-width: 720px`,
no existing sidebar or two-pane structure. One media query exists today
(`max-width: 480px`, cosmetic only).

**Not present yet:** rename, and anything resembling a persistent
(non-modal) panel.

## Scope decision (confirmed with Henry)

Build the new sidebar as an **additional** UI element — `#pastConvPanel`
stays as-is, untouched. This means once this ships there will be two ways
to reach the same conversation list (the sidebar, and the old "Past
conversations" button). That duplication is accepted for now rather than
resolved; flagging it here so it doesn't read as an oversight later. A
follow-up cleanup pass (retire the old button/panel once the sidebar is
validated) is a reasonable Phase 2, not part of this plan.

## Target design

- **Sidebar**: fixed-width column to the left of the main chat column,
  visible by default on wide viewports. Lists conversations newest-first,
  reusing `loadConversationIndex()` as the data source — same 20-entry cap,
  same `{sessionId, startedAt, title, persona}` shape, plus a new optional
  `renamedTitle` field (see Data model below).
- **Each row shows**: title (renamed title if set, else the auto-derived
  one), formatted timestamp, persona tag — visually similar to the existing
  `.past-conv-entry` row, reused rather than redesigned.
- **Active session** gets a distinct row state (background/border), driven
  by `state.sessionId`.
- **Rename**: inline edit — click a pencil/rename affordance on the row (or
  double-click the title), swap the title span for a text input, commit on
  blur/Enter, cancel on Escape. Persists to a new `renamedTitle` field so
  the original auto-derived `title` is never destructively overwritten
  (keeps `recordNewConversation`'s existing write path untouched).
- **Delete**: reuse `removeStoredConversation` + the existing nested-button
  `stopPropagation` pattern so deleting a row never also opens it.
- **Collapse control**: a toggle button (persistent, not just for mobile)
  so the sidebar can be manually hidden on wide screens too — collapsed
  state persisted to a new `localStorage` key (e.g.
  `talkback:sidebarCollapsed`) so it survives reload, same pattern already
  used for `STORAGE_KEY_PERSONA`/`STORAGE_KEY_HUMOR`.
- **New conversation**: a row/button at the top of the sidebar that clears
  `state.sessionId` and the log, equivalent to the existing `clearBtn`
  ("Clear conversation") but reachable from the sidebar.

## Responsive behavior

- **Wide viewports**: sidebar rendered inline, pushing the main column
  (not overlaying it) — requires `.shell` to move from a single centered
  block to a flex row (`.app-layout { display: flex }` wrapping a new
  `.sidebar` and the existing `.shell` content). This is the biggest
  structural change: today's CSS assumes one column everywhere.
- **Narrow viewports**: sidebar hidden by default, replaced by a hamburger/
  menu button in `.app-nav` (next to the existing wordmark). Tapping it
  opens the sidebar as an overlay (fixed position, slide-in, backdrop) so
  it doesn't need to permanently steal width from the 720px chat column on
  small screens.
- **Breakpoint**: propose reusing something close to the existing
  `max-width: 480px` query's spirit but widened — sidebars typically need
  more room than a phone in portrait allows alongside a usable chat column,
  so recommend `max-width: 768px` as the collapse point (open decision,
  flagged below).
- Respect the existing `@media (prefers-reduced-motion: reduce)` block —
  any slide-in transition needs to be included in that query, not added as
  a separate untested animation path.

## Data model changes

- Add `renamedTitle: string | null` to each conversation-index entry.
  Display logic becomes `entry.renamedTitle || entry.title || "Untitled
  conversation"`. No migration needed — existing stored entries just lack
  the field, which reads as falsy.
- New `localStorage` key `talkback:sidebarCollapsed` (`"1"`/`"0"` or
  boolean-ish string, matching the existing simple string-value pattern
  used by `STORAGE_KEY_PERSONA`).

## Accessibility

- Sidebar toggle button: `aria-expanded`, `aria-controls` pointing at the
  sidebar's id — same pattern already used on `historyBtn`/`pastConvBtn`.
- Overlay mode (narrow viewports): trap focus while open, close on
  Escape and on backdrop click, return focus to the menu button on close.
- Rename input: labelled via `aria-label` (row has no visible `<label>`),
  and the swap from span to input shouldn't shift focus away
  unexpectedly.
- Row buttons stay real `<button>` elements (matching the existing
  `.past-conv-entry` choice) so the whole sidebar is keyboard-navigable
  without extra tabindex plumbing.

## Open decisions (need Henry's call before/at build time)

1. **Breakpoint value** — 768px proposed above; not verified against any
   design reference, just a reasonable guess.
2. **Push vs. overlay on wide screens** — plan assumes push (sidebar takes
   real layout width, main column narrows). Could instead overlay even on
   wide screens if 720px main-column width is meant to stay fixed.
3. **Collapsed-by-default state** — first-time visitors: sidebar open or
   collapsed? Proposed: open by default, matching "sidebar as primary nav"
   intent implied by the request.
4. **Relationship to `#historyPanel`** ("Conversation history", the
   *current*-session read-only turn browser) — left untouched by this
   plan since it serves a different purpose (browsing the live session's
   turns, not switching between sessions), but worth confirming that
   reading is correct.
5. **New-conversation affordance duplication** — the sidebar's proposed
   "new conversation" control does roughly what `clearBtn` already does;
   worth deciding whether `clearBtn` gets removed from the controls row
   once the sidebar ships, or both stay (same duplication tension as the
   `#pastConvPanel` decision above).

## Implementation steps (once approved)

1. CSS: introduce `.app-layout` flex wrapper, `.sidebar` column, toggle
   button styles, and the new breakpoint's overlay/backdrop styles —
   additive only, no changes to existing `.history-panel`/`.past-conv-*`
   rules.
2. HTML: add the sidebar markup (toggle button in `.app-nav`, `<aside>`
   sidebar with list container + collapse control) without touching
   `#pastConvPanel`/`#historyPanel` markup.
3. JS: add `renderSidebarList()` (parallel to existing `renderPastConvList`,
   ideally sharing a row-building helper rather than duplicating the
   `document.createElement` block wholesale), rename handlers, the
   collapsed-state persistence, and wiring so selecting a sidebar row calls
   the existing `openPastConversation`/resume path rather than a new one.
4. Wire "new conversation" to the same logic `clearBtn`'s handler already
   runs.
5. Manual test pass: wide-viewport push layout, narrow-viewport overlay,
   keyboard-only navigation through rename/delete/open, reduced-motion
   respected, rename persists across reload, delete from sidebar stays in
   sync with `#pastConvPanel`'s list (same underlying storage key).

## Verification plan

- No backend involved — this is frontend-only, `localStorage`-only, so no
  pytest suite to extend.
- `node --check` on the extracted `<script>` block (matches this project's
  existing validation habit per the imported project memory).
- Manual jsdom or browser check: confirm two tabs both reading
  `talkback:conversations` don't clobber each other's rename in a way
  that's worse than the existing delete/clear-all behavior already
  tolerates (last-write-wins is already implicit in the current code —
  not a new problem introduced here, just worth confirming it isn't made
  worse).
