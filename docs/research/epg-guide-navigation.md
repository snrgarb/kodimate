# EPG/TV guide grid navigation: how well-regarded implementations handle D-pad focus

Question: how do frictionless TV-guide grids carry the cursor across rows (Up/Down) and across
time (Left/Right)? Primary sources: Kodi's `CGUIEPGGridContainer` C++ source (github.com/xbmc/xbmc,
`master`, fetched raw) and Android TV's AOSP `packages/apps/TV` guide sources. TiviMate is
closed-source with no official docs, so its section is explicitly inferred and flagged.

## 1. Kodi `CGUIEPGGridContainer`

Source: [`GUIEPGGridContainer.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/GUIEPGGridContainer.cpp), `.h`, [`GUIEPGGridContainerModel.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/GUIEPGGridContainerModel.cpp) (master, fetched 2026-09-16), and [`GUIControlFactory.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/guilib/GUIControlFactory.cpp) for skin attributes.

**Cursor model.** The grid tracks `m_channelCursor`/`m_channelOffset` (row/page-scroll) and
`m_blockCursor`/`m_blockOffset` (column-in-blocks/page-scroll), plus `m_blockTravelAxis` — a
*separate*, sticky value updated only on explicit Left/Right/paging moves, holding "the block
column the cursor should try to stay on." Vertical moves call `UpdateBlock(bUpdateBlockTravelAxis
=false)`, leaving it untouched.

**(a) Up/Down carries the visible column, not the programme's start time.** `SetChannel(int
channel)` looks up `m_gridModel->GetGridItem(channelIndex, m_blockTravelAxis)` — whichever
programme occupies the *same block column* (a viewport-relative position) on the target row —
then `UpdateBlock` re-derives `m_blockCursor` from that item's start, clamped into the page.
Since `m_blockTravelAxis` is always inside the visible page, the landed-on row is guaranteed
on-screen: a programme that started hours earlier is found correctly because the lookup is keyed
by visible column, never by an absolute time that could be off-screen.

**(b) Left/Right: minimal bring-into-view, page-scroll only at the edge, capped by loaded data.**
If the current item isn't first/last on the page, `SetItem(GetPrevItem()/GetNextItem())` just
moves within the page — no scroll. Only at the page edge does it scroll, via
`ScrollToBlockOffset(m_blockOffset ± GetBlockScrollOffset())` where `GetBlockScrollOffset() == 60 /
m_minutesPerBlock` — **exactly one hour**, never a snap to the target's absolute start or a full
page jump. `ScrollToBlockOffset` clamps `offset` to `[0, GridItemsSize() - blocksPerPage]` — it
can never scroll past the *loaded* grid data, and the model itself never sets `m_gridStart` later
than "now minus `GetGridStartPadding()` minutes" — so the cap on scrolling into the past is a
property of the loaded data window, not a separate UI rule.

**(c) "Now" anchoring.** `GoToNow()` → `GoToDate(now)` computes `GetPageNowOffset()` (from
`GetGridStartPadding() / minutesPerBlock`) and scrolls so "now" sits at that fixed offset from the
page's left edge — a small amount of past is always visible, never zero. `m_gridStart` rounds down
to the current/previous half hour. `GoToNow()` runs on load and via `REMOTE_0`/`JumpToNow()`.

**(d) Extra controls** (`OnAction`, `GUIEPGGridContainer.cpp:442-627`): `ACTION_NEXT_ITEM`/
`ACTION_PREV_ITEM` skip **exactly ±12h**; `REMOTE_0` → `GoToNow()`; `ACTION_PAGE_UP`/
`ACTION_PAGE_DOWN` page by a full `blocksPerPage`/`channelsPerPage`, snapping to the first/last
item instead of no-op at the ends; `ACTION_TELETEXT_RED/GREEN/BLUE/YELLOW` and
`ACTION_SCROLL_UP/DOWN` give analog half-/quarter-page scrolling for wheel remotes. Skin-tunable
via `<timeblocks>` (default **36** visible blocks) and `<rulerunit>` (default **12**, tick every
N blocks); default `minutesPerTimeBlock` is **5 min**, giving a 3-hour page ticked hourly — the
same page width Kodimate targets, at finer granularity.

**(e) Visual conventions.** The C++ container only positions items; skins draw the now-line,
past/future dimming, and focus highlight. The channel column is a separate native list scrolling
independently of the programme grid — confirming "fixed channel column" as the standard model.

**(f) Animation.** Scroll position is float-interpolated every frame toward the target at a rate
derived from `m_scrollTime` (a skin-supplied value defaulting to `1`, i.e. effectively instant if
unset) — a continuous scroll, not one fixed-duration tween. No single citable "Kodi default ms"
figure exists for the EPG grid specifically (unconfirmed/inferred beyond the source itself).

## 2. Android TV Live Channels (AOSP `packages/apps/TV`)

Source: [`ProgramManager.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/ProgramManager.java), [`ProgramRow.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/ProgramRow.java), [`ProgramGrid.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/ProgramGrid.java), [`GuideUtils.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/GuideUtils.java) (branch `main`, fetched 2026-09-16), `res/values/integers.xml`.

**(a) Up/Down carries a horizontal *pixel range*, clamped, never the programme's start time.**
`ProgramGrid` keeps `mFocusRangeLeft`/`mFocusRangeRight` (`getFocusRange()`), narrowed on every
horizontal move by intersecting the focused view's rect with the previous range
(`updateUpDownFocusState`), clamped to `getRightMostFocusablePosition()` so it can never point
off-screen. On Up/Down, `ProgramRow.onRequestFocusInDescendants` calls
`GuideUtils.findNextFocusedProgram(row, focusRangeLeft, focusRangeRight,
keepCurrentProgramFocused)`, which picks: (1) the live/current programme if
`keepCurrentProgramFocused`; else (2) whichever programme fully contains the old range; else (3)
the widest one fully inside it; else (4) the largest-overlap one. **A long programme that started
before the viewport is simply matched by overlap** — its start time never enters the lookup, so
nothing goes off-screen.

**(b) Left/Right: minimal bring-into-view, capped at each end.** `ProgramRow.focusSearch` only
calls `scrollByTime` when the target's start/end falls outside (or near the edge of) the current
window, capped `Math.max(-ONE_HOUR_MILLIS, ...)`/`Math.min(ONE_HOUR_MILLIS, ...)` — **at most one
hour per move**, never a jump to the target's absolute start. `ProgramManager.shiftTime()` clamps
both `mFromUtcMillis`/`mToUtcMillis` to `[mStartUtcMillis, mEndUtcMillis]` — `mStartUtcMillis` (set
once, ≈"now") is a hard floor the guide can never scroll before; `mEndUtcMillis` (loaded EPG
horizon) is the hard ceiling.

**(c) "Now" anchoring.** `mStartUtcMillis` is also the initial `fromUtcMillis`, so the guide opens
with its left edge at "now" and is architecturally unable to move earlier.

**(d)/(f) Paging and animation.** `program_guide_anim_duration = 250` (ms) drives show/hide,
row-selection, and detail-panel tweens; `program_guide_selection_row = 2` fixes which on-screen
row stays the "resting" selection row while scrolling channels. No dedicated horizontal-scroll
duration constant exists — that rides on `RecyclerView`/`LinearLayoutManager` fling physics
(inferred from its absence in `TimelineGridView`).

## 3. TiviMate (inferred — no primary source available)

Closed-source, no public API/UX spec; everything below is inferred from user-facing
walkthroughs, not verified source, and flagged as such: Up/Down scrolls channels, with holding
the key reported to auto-repeat (**inferred**); colour/shortcut buttons are commonly described as
day-skip or "jump to now" shortcuts in this class of app, and TiviMate is reported to support a
"jump to now" action but its exact trigger is **unconfirmed**; long-press on a future programme
opens scheduling, not navigation (**inferred**, well corroborated). No citable rule was found for
how TiviMate resolves a long programme across rows or how far it caps scroll-back — treat it as
directional inspiration for *what controls exist*, not as an algorithm source.

## Recommended rules for Kodimate

Both known bugs share one root cause: the cursor is tracked as an absolute **time**
(`self._cursor_time`) instead of a **viewport-relative position**, so a legitimately off-screen
target (an old long programme, or a distant start time) drags the whole viewport with it. Kodi's
`m_blockTravelAxis` and Android TV's `focusRange` both solve this by tracking where the cursor
sits on screen and deriving the underlying programme separately per move.

1. **Replace `self._cursor_time` as the value carried across rows with a viewport-relative column**
   (matching `m_blockTravelAxis`). On Up/Down, look up whichever programme occupies that same
   on-screen column on the target row (`viewport_start + cursor_column * slot_width`, clamped to
   the viewport) — never the previous row's programme start. Fixes bug (1): the result is always
   on-screen, so Up/Down alone never triggers a viewport jump.
2. **Update the cursor column only on explicit Left/Right/paging, never on Up/Down** — mirror
   `SetBlock`'s `bUpdateBlockTravelAxis` split. `move_cursor_vertical` should resolve against the
   clamped column and never write back a value that could be off-screen.
3. **Cap the horizontal viewport jump; stop snapping to the target's absolute start.** Fixes bug
   (2): replace the current `round_down_30_local(target_start)` jump (Kodi's rejected naive
   approach) with a minimal-bring-into-view shift — align the target programme's near edge to the
   viewport edge, capped at one page width (`VISIBLE_HOURS`) per move. This is a deliberate,
   flagged **deviation** from the spec's current wording ("jumps to the nearest 30-minute
   boundary, uncapped"): keep the 30-minute grid-alignment (Kodi does the same), drop "uncapped."
4. **Clamp viewport starts to a floor of "now minus a small fixed padding" and a ceiling at the
   EPG retention window**, matching Kodi's `GetGridStartPadding()` floor and Android TV's
   `mStartUtcMillis`/`mEndUtcMillis` clamp. Kodimate already fixes retention at 7 days; add an
   explicit floor (e.g. viewport cannot start earlier than "now minus 30–60 min") so Left/skip
   actions can't wander into near-empty history.
5. **Keep Up/Down cheap (`_swap_cursor_row`-style) whenever the target lands in an already-loaded,
   on-screen cell** — already matches both primary sources' "resolve within the page, no scroll"
   behavior; just ensure rule 1's column-based lookup still finds a same-row cell without forcing
   `_relayout()`.
6. **Consider an explicit "jump to now" control** (Kodi's `REMOTE_0`/colour-button convention) as
   a new-scope suggestion, not required by the two bugs — confirm against the spec's "Guide grid"
   paragraph before implementing, since it isn't mentioned there today.

## Sources

- [`GUIEPGGridContainer.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/GUIEPGGridContainer.cpp) / [`.h`](https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/GUIEPGGridContainer.h) (xbmc/xbmc, master)
- [`GUIEPGGridContainerModel.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/GUIEPGGridContainerModel.cpp)
- [`GUIControlFactory.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/guilib/GUIControlFactory.cpp) (`timeblocks`/`rulerunit`/`minutesPerTimeBlock` parsing)
- [`ProgramManager.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/ProgramManager.java) (AOSP, branch `main`)
- [`ProgramRow.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/ProgramRow.java)
- [`ProgramGrid.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/ProgramGrid.java)
- [`GuideUtils.java`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/src/com/android/tv/guide/GuideUtils.java)
- [`res/values/integers.xml`](https://android.googlesource.com/platform/packages/apps/TV/+/refs/heads/main/res/values/integers.xml)
- TiviMate: no primary source; corroboration only from [tivimates.net remote guide](https://tivimates.net/tivimate-remote/), [Toms Guide forum thread](https://forums.tomsguide.com/threads/page-up-down-in-guide.249267) — inferred/unconfirmed throughout §3.
- Local repo: `resources/lib/kodimate/guide.py`, `resources/lib/kodimate/windows/guide.py`, `docs/spec/kodimate-v1.md` ("**Guide grid**" paragraph).
