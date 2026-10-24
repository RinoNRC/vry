# Changelog

## v2.94 - GUI preview

- Keep Pygments in frozen builds for Rich imports; verify the Windows executable opens with isolated local data.

- Keep scroll containers and their parent layouts mounted during background refreshes; restore tab positions once, cancel stale restores on user scroll/navigation, and remove repeated drawer scroll resets.

- Group settings into four categories with native switches, calmer section styling, clearer statistic/notification descriptions and confirmed reset; restore switch/rank-style controls after failed writes.

- Redesign the match header around map/phase/server, remove duplicate team labels and distinguish starting attack/defense from unavailable live-side tracking; resolve pregame own team from AllyTeam or roster membership.

- Refresh the slate palette and soften team/self highlights; add consistent, subtle HS%/WR/KD/ADR color scales with threshold hints and neutral missing data.
- Redesign the player drawer with separated statistic sources, local encounters and collapsible skins.
- Modernize history with map thumbnails, personal K/D/A, responsive filters and clearer roster details; never infer unavailable match outcomes.

- Load live dashboard HS% and K/D from the latest completed competitive match in the background for faster results.
- Label the statistics source; keep selected-match history separate.
- Fix party grouping from flat/nested presence data and the existing own-party roster; show consistent colored party badges in menus, agent select, and matches.
- Show confirmed party groups in completed-match history from exact-match results, enrich recent legacy records, and distinguish unknown party data from solo play.
- Reuse latest-match statistics during agent-select/game transitions; cache and batch player-name requests.
- Bound network retries, verify remote TLS, and handle missing/malformed API responses safely.
- Keep optional skin/reference-catalog failures from stopping ranks and statistics.
- Recover invalid settings with a backup; save settings atomically and reload changes in the monitor loop.
- Refresh diagnostics without treating a quiet match as a disconnected client.
- Save pending history on normal shutdown/disconnect, clear stale disconnected views, and bound chat caches.
- Disable the legacy upstream updater in the GUI and run regression tests before CI builds.

- Added a Flet desktop GUI with a frameless Windows window.
- Added live match, history, diagnostics, account and settings views.
- Added local player loadouts and skin inspection without an external viewer.
- Added rank badges, team panels, team averages and rank sorting.
- Added local history, repeat encounter indicators and match details.
- Added Windows system notifications for match start.
- Added Discord Rich Presence with party size, map, phase timer and server.
- Added animated backgrounds, transitions, shimmer loading and responsive layouts.
- Removed the external mobile WebSocket viewer.
- Added original vRY branding assets.

## Planned

- Public signed release channel and verified updater.
- More complete match history and export tools.
