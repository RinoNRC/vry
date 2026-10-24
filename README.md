# vRY // VALORANT Companion

Desktop-first VALORANT companion with live lobby intelligence, ranks, agents,
loadouts, local history, diagnostics, account context and Discord Rich Presence.

> This is an independent community project by `RinoNRC`. It is not affiliated
> with or endorsed by Riot Games.

Based on [VALORANT-rank-yoinker](https://github.com/zayKenyon/VALORANT-rank-yoinker)
by Zay Kenyon and contributors. This version adds the desktop GUI and companion
features; the original ISC license and copyright notice are preserved in [LICENSE](LICENSE).

## Features

- Flet GUI with a frameless Windows desktop window and no console.
- Live match dashboard with team panels, rank sorting and agent thumbnails.
- Current, peak and previous rank, RR, HS%, WR, K/D and account level.
- Local loadout inspection inside the player details panel.
- Match history, repeat encounters, activity charts and match details.
- Account view with rank progress, recent statistics and current session data.
- Diagnostics with connection timeline, heartbeat graph and safe event log.
- Windows system notifications for match start.
- Discord Rich Presence with phase timer, map, server and party size.
- No external mobile WebSocket viewer is required.

## Interface

- Neutral slate surfaces with softly colored HS%, WR, K/D and ADR values:
  muted red for low, amber for medium and green for high, with subtle table fills.
  Thresholds are illustrative rather than a skill rating; hover for the scale.
  RR changes use gain/loss colors; RR totals, levels and leaderboard stay neutral.
- The match header prioritizes map, phase, server and a single starting-side
  badge (standard modes: Red starts attack, Blue starts defense). This is not
  the current side: halftime/overtime changes are not tracked. Unsupported
  modes and missing assignments show no side data.
- Settings are grouped into Display, Match/Launch, Notifications and About,
  with native switches, automatic saving and a confirmation before resetting.
  Failed writes restore the previous control value; reset never clears history.
- The player drawer separates ranks, latest competitive-match HS%/K/D, current
  act statistics, local encounters and collapsible skins, with explicit sources.
- History cards show map, mode, date and your own K/D/A, not totals across all
  players. Missing outcomes remain neutral; match detail keeps team rosters and
  confirmed party badges.

## Usage

VALORANT must be open for live data.

Live lobby HS% and K/D come from each player's latest completed competitive
match, clearly labelled in the dashboard and player details. Loading runs in
the background, fetching only one match per player for faster results.
HS% uses head hits / total hits; K/D uses kills / deaths in that match.
Unavailable/private data remains `—`, with status in the tooltip.
WR remains the current act's win rate. Successful latest-match results are
reused during agent-select/game transitions within the same match; returning
to menus invalidates them so the next match can be discovered. Player-name
requests are batched and cached for up to five minutes.

Network retries are bounded. Optional cosmetic catalogs may be unavailable
without disabling ranks/statistics. Settings are saved atomically; monitor
settings are reloaded during the WebSocket wait as well as at loop entry.
The GUI does not invoke
the legacy upstream updater.

History HS%, K/D, K/D/A and ADR belong to the selected match, never to the
recent-match aggregate. The match-details API publishes these results after
the match; while unavailable the app shows `—`. Recent incomplete local history
is repaired in the background, with bounded retries when publication is delayed.
History collection is independent of which statistics columns are visible.
Party badges in completed-match details use that exact match's `partyId`
values, never a player's previous match or the current lobby. Members of a
confirmed group share a badge and color. Older saved matches in the latest
30-match window are enriched by the existing history worker; missing party
fields are recorded as unavailable rather than retried indefinitely.
Live badges remain limited to confirmed client-visible groups; no badge does
not mean the player queued solo.
Before the first history write, the existing `stats.json` is copied to
`stats.json.bak` in `%APPDATA%/vry`.

### Bundled release

1. Download Microsoft Visual C++ Libraries if required by Windows.
2. Download the latest GitHub release archive.
3. Extract the complete archive.
4. Run `vry.exe`.

### Running from source

1. Install Python 3.10 or 3.11 and add it to PATH.
2. Download this repository.
3. Run `INSTALL.bat` to create `.venv` and install the dependencies there.
4. Run `START.bat`; it automatically uses `.venv` when present and reports missing dependencies.

For a manual installation, use `pip install -r requirements.txt` and
`python gui_main.py` with the same Python environment.

### Building from source

```powershell
pip install -r requirements.txt
pip install cx_Freeze
python setup.py build
```

The complete output folder is required. Do not distribute only `vry.exe`.

## GitHub Actions

Pushes to `main` and version tags build a Windows artifact through
`.github/workflows/build.yml`. The workflow installs pinned dependencies,
builds with cx_Freeze and uploads the complete folder as an artifact.

## Privacy and policy

vRY reads local Riot Client session data and stores history locally. It does
not require an external mobile viewer. Streamer mode is respected. Never
share `config.json`, logs, account data, lockfile credentials or entitlement
tokens.

The project uses unofficial/public APIs and is provided at the user's own risk.

## Contributing

See `CONTRIBUTING.md`. Issues and pull requests are welcome. Do not add code
that exposes hidden player data, credentials or cookies.

## Contact

Creator: `RinoNRC`  |  Telegram: [@rinonrc](https://t.me/rinonrc)

## Acknowledgements

- [Valorant-API.com](https://valorant-api.com/)
- [Flet](https://flet.dev/)
- [pypresence](https://github.com/qwertyquerty/pypresence)

## Disclaimer

VALORANT is a trademark of Riot Games. vRY is not associated with or endorsed
by Riot Games. Use of this software is at your own risk.
