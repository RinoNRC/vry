class Pregame:
    def __init__(self, Requests, log):
        self.log = log
        self.Requests = Requests
        self.match_id = 0

    def get_pregame_match_id(self):
        response = self.Requests.fetch("glz", f"/pregame/v1/players/{self.Requests.puuid}", "get")
        self.match_id = response.get("MatchID") if isinstance(response, dict) and not response.get("errorCode") else 0
        self.match_id = self.match_id or 0
        return self.match_id

    def get_pregame_stats(self):
        match_id = self.get_pregame_match_id()
        if not match_id:
            return None
        data = self.Requests.fetch("glz", f"/pregame/v1/matches/{match_id}", "get")
        if not isinstance(data, dict) or not isinstance(data.get("AllyTeam"), dict):
            return None
        if not isinstance(data["AllyTeam"].get("Players"), list) or not data.get("Teams"):
            return None
        return data
