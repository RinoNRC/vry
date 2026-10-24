def normalize_party_id(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 128 or value == "00000000-0000-0000-0000-000000000000":
        return None
    return value


def history_party_labels(players):
    groups = {}
    for puuid, player in players.items():
        party_id = normalize_party_id(player.get("partyId"))
        if player.get("partyResolved") is True and party_id:
            groups.setdefault(party_id, []).append(puuid)
    groups = {party_id: members for party_id, members in groups.items() if len(members) > 1}
    labels = {}
    for number, party_id in enumerate(sorted(groups), start=1):
        members = groups[party_id]
        for puuid in members:
            labels[puuid] = {"partyNumber": number, "partySize": len(members)}
    return labels
