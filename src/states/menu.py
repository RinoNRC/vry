from src.presences import Presences


class Menu:
    def __init__(self, Requests, log, presences):
        self.Requests = Requests
        self.log = log
        self.presences = presences

    def get_party_json(self, GamePlayersPuuid, presencesDICT, own_party_members=None):
        party_json = {}
        players = GamePlayersPuuid if isinstance(GamePlayersPuuid, (list, tuple, set, dict)) else []
        player_parties = {}
        for presence in self._presence_entries(presencesDICT):
            puuid = presence.get("puuid")
            if not isinstance(puuid, str) or puuid not in players:
                continue
            decoded = Presences.decode_private(presence.get("private"))
            party_id, _ = self._party_fields(decoded)
            if party_id:
                player_parties[puuid] = party_id
        for puuid, party_id in player_parties.items():
            party_json.setdefault(party_id, []).append(puuid)

        if isinstance(own_party_members, list):
            own_ids = {member.get("Subject") for member in own_party_members
                       if isinstance(member, dict) and isinstance(member.get("Subject"), str)}
            self_puuid = self.Requests.puuid
            if isinstance(self_puuid, str) and self_puuid in own_ids and self_puuid in players:
                own_key = player_parties.get(self_puuid)
                party_json = {key: [puuid for puuid in members if puuid not in own_ids]
                              for key, members in party_json.items() if key != own_key}
                party_json[f"own:{self_puuid}"] = sorted(own_ids.intersection(players))

        party_json = {party: members for party, members in party_json.items() if len(members) > 1}
        self.log(f"retrieved party json: {len(party_json)} parties")
        return party_json

    @staticmethod
    def get_party_labels(party_json):
        labels = {}
        for number, party_id in enumerate(sorted(party_json), start=1):
            members = party_json[party_id]
            for puuid in members:
                labels[puuid] = {"partyNumber": number, "partySize": len(members)}
        return labels

    @staticmethod
    def _presence_entries(presences):
        if not isinstance(presences, list):
            return []
        return [presence for presence in presences if isinstance(presence, dict)
                and presence.get("championId") is None
                and presence.get("product") != "league_of_legends"]

    @staticmethod
    def _account_level(level):
        return level if isinstance(level, int) and not isinstance(level, bool) and level >= 0 else 0

    @staticmethod
    def _party_fields(decoded_presence):
        if not isinstance(decoded_presence, dict) or decoded_presence.get("isValid") is False:
            return None, 0

        party_data = Presences.presence_section(decoded_presence, "partyPresenceData")
        player_data = Presences.presence_section(decoded_presence, "playerPresenceData")
        party_id = party_data.get("partyId")
        if not isinstance(party_id, str) or not party_id.strip() or party_id.strip() == "00000000-0000-0000-0000-000000000000":
            party_id = None
        else:
            party_id = party_id.strip()
        return party_id, Menu._account_level(player_data.get("accountLevel"))

    def _get_party_members_from_api(self, self_puuid):
        try:
            player_party = self.Requests.fetch(
                url_type="glz",
                endpoint=f"/parties/v1/players/{self_puuid}",
                method="get",
            )
            party_id = player_party.get("CurrentPartyID") if isinstance(player_party, dict) else None
            if not isinstance(party_id, str) or not party_id:
                return None

            party_data = self.Requests.fetch(
                url_type="glz",
                endpoint=f"/parties/v1/parties/{party_id}",
                method="get",
            )
            members = party_data.get("Members") if isinstance(party_data, dict) else None
            if not isinstance(members, list):
                return None

            result = []
            seen = set()
            for member in members:
                if not isinstance(member, dict):
                    continue
                puuid = member.get("Subject") or member.get("subject")
                if not isinstance(puuid, str) or not puuid or puuid in seen:
                    continue
                identity = member.get("PlayerIdentity") or member.get("playerIdentity") or {}
                if not isinstance(identity, dict):
                    identity = {}
                result.append({
                    "Subject": puuid,
                    "PlayerIdentity": {
                        "AccountLevel": self._account_level(identity.get("AccountLevel", identity.get("accountLevel", 0)))
                    },
                })
                seen.add(puuid)
            return result or None
        except Exception:
            self.log("Unable to fetch party roster from GLZ API.")
            return None

    def get_party_members(self, self_puuid, presencesDICT):
        if not isinstance(self_puuid, str) or not self_puuid:
            return []
        api_members = self._get_party_members_from_api(self_puuid)
        if api_members is not None:
            self.log(f"retrieved party members from GLZ API: {len(api_members)}")
            return api_members

        presencesDICT = self._presence_entries(presencesDICT)
        self_presence = next(
            (presence for presence in presencesDICT if presence.get("puuid") == self_puuid),
            None,
        )
        if not self_presence:
            self.log("Party roster unavailable: own presence was not found.")
            return []

        try:
            own_decoded = Presences.decode_private(self_presence.get("private"))
        except (TypeError, ValueError, KeyError):
            own_decoded = None
        party_id, account_level = self._party_fields(own_decoded)
        if not party_id:
            self.log("Party roster unavailable: own presence has no party ID.")
            return []

        result = [{
            "Subject": self_puuid,
            "PlayerIdentity": {"AccountLevel": account_level},
        }]
        seen = {self_puuid}
        for presence in presencesDICT:
            puuid = presence.get("puuid")
            if not isinstance(puuid, str) or not puuid or puuid in seen:
                continue
            try:
                decoded = Presences.decode_private(presence.get("private"))
            except (TypeError, ValueError, KeyError):
                continue
            current_party_id, member_level = self._party_fields(decoded)
            if current_party_id == party_id:
                result.append({
                    "Subject": puuid,
                    "PlayerIdentity": {"AccountLevel": member_level},
                })
                seen.add(puuid)

        self.log(f"retrieved party members from presence fallback: {len(result)}")
        return result
