import base64
import binascii
import json


class Presences:
    def __init__(self, Requests, log):
        self.Requests = Requests
        self.log = log

    def get_presence(self):
        response = self.Requests.fetch(url_type="local", endpoint="/chat/v4/presences", method="get")
        if not isinstance(response, dict) or not isinstance(response.get("presences"), list):
            return None
        return response["presences"]

    @staticmethod
    def decode_private(private):
        if isinstance(private, dict):
            return private
        if not isinstance(private, (str, bytes)) or not private:
            return None
        try:
            raw = private.strip()
            json_prefixes = ("{", "[") if isinstance(raw, str) else (b"{", b"[")
            if not raw.startswith(json_prefixes):
                raw = base64.b64decode(raw, validate=True)
            decoded = json.loads(raw)
        except (ValueError, TypeError, UnicodeError, binascii.Error):
            return None
        return decoded if isinstance(decoded, dict) else None

    @staticmethod
    def presence_section(private, section):
        if not isinstance(private, dict):
            return {}
        nested = private.get(section)
        if isinstance(nested, dict):
            return {**private, **nested}
        return private

    @staticmethod
    def game_state(private):
        state = Presences.presence_section(private, "matchPresenceData").get("sessionLoopState")
        return state if isinstance(state, str) and state else None

    def get_game_state(self, presences):
        return self.game_state(self.get_private_presence(presences))

    def get_private_presence(self, presences):
        if not isinstance(presences, list):
            return None
        for presence in presences:
            if not isinstance(presence, dict) or presence.get("puuid") != self.Requests.puuid:
                continue
            if presence.get("championId") is not None or presence.get("product") == "league_of_legends":
                continue
            decoded = self.decode_private(presence.get("private"))
            if decoded is not None:
                return decoded
        return None

    def decode_presence(self, private):
        decoded = self.decode_private(private)
        if decoded and decoded.get("isValid") is True:
            return decoded
        return {
            "isValid": False,
            "partyId": 0,
            "partySize": 0,
            "partyVersion": 0,
        }

    def wait_for_presence(self, PlayersPuuids):
        # Compatibility snapshot only; name resolution does not require presence polling.
        return self.get_presence()
