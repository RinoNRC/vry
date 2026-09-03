# vRY // VALORANT Companion

Desktop-first VALORANT companion with live lobby intelligence, ranks, agents,
loadouts, local history, diagnostics, account context and Discord Rich Presence.

> This is an independent community project by `RinoNRC`. It is not affiliated
> with or endorsed by Riot Games.

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

## Usage

VALORANT must be open for live data.

### Bundled release

1. Download Microsoft Visual C++ Libraries if required by Windows.
2. Download the latest GitHub release archive.
3. Extract the complete archive.
4. Run `vry.exe`.

### Running from source

1. Install Python 3.10 or 3.11 and add it to PATH.
2. Download this repository.
3. Run `INSTALL.bat` or `pip install -r requirements.txt`.
4. Run `START.bat` or `python gui_main.py`.

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
