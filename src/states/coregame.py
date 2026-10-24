class Coregame:
    def __init__(self, Requests, log):
        self.log = log
        self.Requests = Requests
        self.match_id = 0

    def get_coregame_match_id(self):
        response = self.Requests.fetch(
            url_type="glz", endpoint=f"/core-game/v1/players/{self.Requests.puuid}", method="get"
        )
        self.match_id = response.get("MatchID") if isinstance(response, dict) and not response.get("errorCode") else 0
        self.match_id = self.match_id or 0
        return self.match_id

    def get_coregame_stats(self):
        match_id = self.get_coregame_match_id()
        if not match_id:
            return None
        data = self.Requests.fetch("glz", f"/core-game/v1/matches/{match_id}", "get")
        if not isinstance(data, dict) or not isinstance(data.get("Players"), list) or not data.get("MapID"):
            return None
        return data

    def get_current_map(self, map_urls, map_splashes):
        data = self.get_coregame_stats()
        if data is None:
            return "N/A"
        current_map = map_urls.get(str(data["MapID"]).lower())
        return {"name": current_map, "splash": map_splashes.get(current_map)}
