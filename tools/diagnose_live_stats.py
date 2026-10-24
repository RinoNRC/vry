"""Read-only API diagnostics. Prints field names/statuses, never credentials or player values."""
import argparse
import base64
import json
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path


COMBAT = re.compile(r"kill|death|assist|headshot|bodyshot|legshot|damage|roundresult|score", re.I)


def get_json(url, headers, local=False):
    request = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl._create_unverified_context() if local else ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            try:
                return response.status, json.load(response)
            except (ValueError, UnicodeError):
                return response.status, None
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return "connection-error", None


def combat_fields(data, prefix="", depth=0):
    if depth > 8:
        return set()
    found = set()
    if isinstance(data, dict):
        for key, value in data.items():
            # Dynamic IDs are not useful schema and must not appear in output.
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
                continue
            path = f"{prefix}.{key}" if prefix else key
            if COMBAT.search(key):
                found.add(path)
            found.update(combat_fields(value, path, depth + 1))
    elif isinstance(data, list):
        for item in data[:20]:
            found.update(combat_fields(item, prefix + "[]", depth + 1))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lockfile", required=True)
    parser.add_argument("--region", choices=("eu", "na", "ap", "kr", "br", "latam"), required=True)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z]{2,5}-[0-9]+", args.shard):
        parser.error("invalid shard")
    try:
        parts = Path(args.lockfile).read_text(encoding="utf-8").strip().split(":")
        if len(parts) != 5 or not parts[2].isdigit():
            print("Lockfile unavailable or invalid")
            return
        local_url = f"https://127.0.0.1:{int(parts[2])}"
        basic = base64.b64encode(("riot:" + parts[3]).encode()).decode()
    except OSError:
        print("Lockfile unavailable")
        return
    local_headers = {"Authorization": "Basic " + basic}
    status, token = get_json(local_url + "/entitlements/v1/token", local_headers, local=True)
    print("Local session HTTP:", status)
    if not isinstance(token, dict) or not all(token.get(k) for k in ("accessToken", "token", "subject")):
        print("No active authenticated session; no remote requests made")
        return
    platform = base64.b64encode(json.dumps({
        "platformType": "PC", "platformOS": "Windows",
        "platformOSVersion": "10.0.19042.1.256.64bit", "platformChipset": "Unknown",
    }).encode()).decode()
    headers = {
        "Authorization": "Bearer " + token["accessToken"],
        "X-Riot-Entitlements-JWT": token["token"],
        "X-Riot-ClientPlatform": platform,
        "X-Riot-ClientVersion": args.version,
        "User-Agent": "ShooterGame/13 Windows/10.0.19043.1.256.64bit",
    }
    status, presences = get_json(local_url + "/chat/v4/presences", local_headers, local=True)
    print("Local presence HTTP:", status)
    if isinstance(presences, dict):
        for presence in presences.get("presences", []):
            if presence.get("puuid") == token["subject"] and presence.get("product") == "valorant":
                try:
                    private = json.loads(base64.b64decode(presence.get("private", "")))
                    print("Own presence combat/score fields:", sorted(combat_fields(private)))
                except (ValueError, TypeError):
                    print("Own presence payload unavailable")
    glz = f"https://glz-{args.shard}.{args.region}.a.pvp.net"
    status, current = get_json(glz + "/core-game/v1/players/" + token["subject"], headers)
    print("Current match HTTP:", status)
    match_id = current.get("MatchID") if isinstance(current, dict) else None
    if status != 200 or not isinstance(match_id, str) or not re.fullmatch(r"[a-fA-F0-9-]{36}", match_id):
        print("No active match found; combat availability cannot be checked")
        return
    status, match = get_json(glz + "/core-game/v1/matches/" + match_id, headers)
    print("Coregame match HTTP:", status)
    if isinstance(match, dict):
        print("Coregame top-level fields:", sorted(match))
        players = match.get("Players") or []
        print("Coregame player count:", len(players))
        print("Coregame player field names:", sorted({key for p in players if isinstance(p, dict) for key in p}))
        print("Coregame combat/score fields:", sorted(combat_fields(match)))
    status, details = get_json(f"https://pd.{args.region}.a.pvp.net/match-details/v1/matches/" + match_id, headers)
    print("Active match-details HTTP:", status)
    if isinstance(details, dict):
        print("Match-details combat/score fields:", sorted(combat_fields(details)))
        print("Match marked completed:", (details.get("gameInfo") or {}).get("isCompleted"))


if __name__ == "__main__":
    main()
