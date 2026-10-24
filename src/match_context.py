def pregame_own_team(data, puuid):
    ally = data.get("AllyTeam")
    if isinstance(ally, dict) and isinstance(ally.get("TeamID"), str) and ally["TeamID"]:
        return ally["TeamID"]
    teams = data.get("Teams")
    for team in teams if isinstance(teams, list) else []:
        if not isinstance(team, dict):
            continue
        players = team.get("Players")
        if isinstance(players, list) and any(
            isinstance(player, dict) and player.get("Subject") == puuid for player in players
        ):
            return team.get("TeamID")
    return None


def starting_side(heartbeat):
    if heartbeat.get("state") not in {"PREGAME", "INGAME"}:
        return None
    mode = str(heartbeat.get("mode") or "").lower().replace(" ", "")
    if mode not in {"competitive", "unrated", "swiftplay", "spikerush", "premier"}:
        return None
    return {"blue": "defense", "red": "attack"}.get(str(heartbeat.get("ownTeam") or "").lower())
