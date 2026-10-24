import time
import requests
from colr import color
from src.constants import sockets, hide_names


class Loadouts:
    def __init__(self, Requests, log, colors, state_store, current_map):

        self.Requests = Requests
        self.log = log
        self.colors = colors
        self.state_store = state_store
        self.current_map = current_map
        self._reference_data_cache = {}
        self._reference_retry_at = 0

    def _get_reference_data(self, resource):
        if resource not in self._reference_data_cache:
            if time.monotonic() < self._reference_retry_at:
                raise ValueError("Reference catalogs temporarily unavailable")
            try:
                response = requests.get(
                    f"https://valorant-api.com/v1/{resource}",
                    timeout=(3, 10),
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("Invalid reference catalog")
                if any(not isinstance(item, dict) for item in payload["data"]):
                    raise ValueError("Invalid reference catalog entries")
                self._reference_data_cache[resource] = payload["data"]
            except Exception:
                # All catalogs share a host; avoid retrying each resource during an outage.
                self._reference_retry_at = time.monotonic() + 15
                raise
        return self._reference_data_cache[resource]

    def get_match_loadouts(self, match_id, players, weaponChoose, valoApiSkins, names, state="game"):
        weaponLists = {}
        final_json = {"Players": {}, "time": int(time.time()), "map": self.current_map}
        try:
            result = self._get_match_loadouts(
                match_id, players, weaponChoose, valoApiSkins, names, state, weaponLists)
            if result is not None:
                final_json = result
        except Exception:
            # Cosmetics are optional; malformed nested data must not stop the monitor.
            pass
        try:
            self.state_store.publish("matchLoadout", final_json)
        except Exception:
            pass
        return [weaponLists, final_json]

    def _get_match_loadouts(self, match_id, players, weaponChoose, valoApiSkins, names, state, weaponLists):
        playersBackup = players
        if state == "game":
            endpoint = "core-game"
        elif state == "pregame":
            endpoint = "pregame"
            players = players["AllyTeam"]["Players"]
        else:
            return None
        PlayerInventorys = self.Requests.fetch(
            "glz", f"/{endpoint}/v1/matches/{match_id}/loadouts", "get")
        if not isinstance(PlayerInventorys, dict) or not isinstance(PlayerInventorys.get("Loadouts"), list):
            return None

        valid_loadouts = []
        loadout_by_subject = {}
        for entry in PlayerInventorys["Loadouts"]:
            if not isinstance(entry, dict):
                continue
            subj = entry.get("Subject")
            inv = entry.get("Loadout") if state == "game" else entry
            if (isinstance(subj, str) and subj and entry.get("CharacterID")
                    and isinstance(inv, dict) and isinstance(inv.get("Items"), dict)):
                valid_loadouts.append(entry)
                loadout_by_subject[subj.lower()] = inv
        if not valid_loadouts:
            return None
        PlayerInventorys = dict(PlayerInventorys, Loadouts=valid_loadouts)
        valApiWeapons = self._get_reference_data("weapons")
        try:
            self._get_weapon_names(players, weaponChoose, valoApiSkins,
                                   valApiWeapons, loadout_by_subject, weaponLists)
        except Exception:
            pass
        return self.convertLoadoutToJsonArray(
            PlayerInventorys, playersBackup, state, names)

    def _get_weapon_names(self, players, weaponChoose, valoApiSkins, valApiWeapons, loadout_by_subject, weaponLists):
        for player in players:
            subj = player.get("Subject", "").lower()
            inv = loadout_by_subject.get(subj)
            if inv is None:
                continue
            for weapon in valApiWeapons:
                if weapon["displayName"].lower() == weaponChoose.lower():
                    skin_id = \
                        inv["Items"][weapon["uuid"].lower()]["Sockets"]["bcef87d6-209b-46c6-8b19-fbe40bd95abc"]["Item"][
                            "ID"]
                    json_data = valoApiSkins.json()
                    if not isinstance(json_data, dict) or not isinstance(json_data.get("data"), list):
                        return
                    for skin in json_data["data"]:
                        if skin_id.lower() == skin["uuid"].lower():
                            rgb_color = self.colors.get_rgb_color_from_skin(
                                skin["uuid"].lower(), valoApiSkins)
                            skin_display_name = skin["displayName"].replace(
                                f" {weapon['displayName']}", "")
                            weaponLists.update({player["Subject"]: color(
                                skin_display_name, fore=rgb_color)})

    # this will convert valorant loadouts to json with player names
    def convertLoadoutToJsonArray(self, PlayerInventorys, players, state, names):
        # These reference catalogs change infrequently; keep them for this process.
        sprays = self._get_reference_data("sprays")
        weapons = self._get_reference_data("weapons")
        buddies = self._get_reference_data("buddies")
        agents = self._get_reference_data("agents")
        titles = self._get_reference_data("playertitles")
        player_cards = self._get_reference_data("playercards")
        sprays_by_id = {item["uuid"].lower(): item for item in sprays if item.get("uuid")}
        weapons_by_id = {item["uuid"].lower(): item for item in weapons if item.get("uuid")}
        buddies_by_id = {item["uuid"].lower(): item for item in buddies if item.get("uuid")}
        agents_by_id = {item["uuid"].lower(): item for item in agents if item.get("uuid")}
        titles_by_id = {item["uuid"].lower(): item for item in titles if item.get("uuid")}
        cards_by_id = {item["uuid"].lower(): item for item in player_cards if item.get("uuid")}

        final_final_json = {"Players": {},
                            "time": int(time.time()),
                            "map": self.current_map}

        final_json = final_final_json["Players"]
        if state == "game":
            PlayerInventorys = PlayerInventorys["Loadouts"]

            # subject (player UUID) -> loadout lookup
            loadout_by_subject = {}
            for entry in PlayerInventorys:
                subj = entry.get("Subject", "").lower()
                # if player has an agent != spectator
                char_id = entry.get("CharacterID", "")
                if subj and char_id:
                    loadout_by_subject[subj] = entry["Loadout"]

            for player in players:
                subject = player["Subject"]
                subj = subject.lower()
                loadout_entry = loadout_by_subject.get(subj)

                final_json.update(
                    {
                        subject: {}
                    }
                )

                # skip if not found
                if loadout_entry is None:
                    continue

                PlayerInventory = loadout_entry

                # creates name field
                if hide_names:
                    agent = agents_by_id.get(str(player.get("CharacterID") or "").lower())
                    if agent:
                        final_json[subject].update({"Name": agent["displayName"]})
                else:
                    final_json[subject].update({"Name": names[subject]})

                # creates team field
                final_json[subject].update({"Team": player["TeamID"]})

                # create spray field
                final_json[subject].update({"Sprays": {}})
                # append sprays to field

                final_json[subject].update(
                    {"Level": player["PlayerIdentity"]["AccountLevel"]})

                identity = player.get("PlayerIdentity") or {}
                title = titles_by_id.get(str(identity.get("PlayerTitleID") or "").lower())
                if title:
                    final_json[subject].update({"Title": title["titleText"]})

                player_card = cards_by_id.get(str(identity.get("PlayerCardID") or "").lower())
                if player_card:
                    final_json[subject].update({"PlayerCard": player_card["largeArt"]})

                agent = agents_by_id.get(str(player.get("CharacterID") or "").lower())
                if agent:
                    final_json[subject].update({"AgentArtworkName": agent["displayName"] + "Artwork"})
                    final_json[subject].update({"Agent": agent["displayIcon"]})

                spray_selections = [
                    s for s in PlayerInventory.get("Expressions", {}).get("AESSelections", [])
                    if s.get("TypeID") == "d5f120f8-ff8c-4aac-92ea-f2b5acbe9475"
                ]
                for j, spray in enumerate(spray_selections):
                    final_json[subject]["Sprays"].update({j: {}})
                    spray_data = sprays_by_id.get(str(spray.get("AssetID") or "").lower())
                    if spray_data:
                        final_json[subject]["Sprays"][j].update({
                            "displayName": spray_data["displayName"],
                            "displayIcon": spray_data["displayIcon"],
                            "fullTransparentIcon": spray_data["fullTransparentIcon"]
                        })

                # create weapons field
                final_json[subject].update({"Weapons": {}})

                for skin in PlayerInventory["Items"]:

                    # create skin field
                    final_json[subject]["Weapons"].update({skin: {}})

                    for socket in PlayerInventory["Items"][skin]["Sockets"]:
                        # predefined sockets
                        for var_socket in sockets:
                            if socket == sockets[var_socket]:
                                final_json[subject]["Weapons"][skin].update(
                                    {
                                        var_socket: PlayerInventory["Items"][skin]["Sockets"][socket]["Item"]["ID"]
                                    }
                                )

                    # create buddy field
                    # self.log("predefined sockets")
                    # final_json[subject]["Weapons"].update({skin: {}})

                    # buddies
                    for socket in PlayerInventory["Items"][skin]["Sockets"]:
                        if sockets["skin_buddy"] == socket:
                            buddy_id = str(PlayerInventory["Items"][skin]["Sockets"][socket]["Item"].get("ID") or "").lower()
                            buddy = buddies_by_id.get(buddy_id)
                            if buddy:
                                final_json[subject]["Weapons"][skin].update(
                                    {"buddy_displayIcon": buddy["displayIcon"]}
                                )

                    weapon = weapons_by_id.get(str(skin).lower())
                    if not weapon:
                        continue
                    final_json[subject]["Weapons"][skin]["weapon"] = weapon["displayName"]

                    sockets_data = PlayerInventory["Items"][skin].get("Sockets", {})
                    skin_id = str(
                        sockets_data.get(sockets["skin"], {}).get("Item", {}).get("ID") or ""
                    ).lower()
                    chroma_id = str(
                        sockets_data.get(sockets["skin_chroma"], {}).get("Item", {}).get("ID") or ""
                    ).lower()
                    skin_data = next(
                        (item for item in weapon.get("skins", []) if item.get("uuid", "").lower() == skin_id),
                        None,
                    )
                    if not skin_data:
                        continue
                    final_json[subject]["Weapons"][skin]["skinDisplayName"] = skin_data["displayName"]
                    chroma = next(
                        (item for item in skin_data.get("chromas", []) if item.get("uuid", "").lower() == chroma_id),
                        None,
                    )
                    if chroma:
                        icon = chroma.get("displayIcon") or chroma.get("fullRender")
                        icon = icon or skin_data.get("displayIcon")
                        if not icon and skin_data.get("levels"):
                            icon = skin_data["levels"][0].get("displayIcon")
                        if icon:
                            final_json[subject]["Weapons"][skin]["skinDisplayIcon"] = icon
                    if skin_data["displayName"].startswith(("Standard", "Melee")):
                        final_json[subject]["Weapons"][skin]["skinDisplayIcon"] = weapon.get("displayIcon")

        return final_final_json
