import requests

class Content():
    def __init__(self, Requests, log):
        self.Requests = Requests
        self.log = log
        self.content = {}
        self._catalogs = {}

    def _public_data(self, resource):
        if resource not in self._catalogs:
            try:
                response = requests.get(f"https://valorant-api.com/v1/{resource}", timeout=(3, 10))
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, list):
                    raise ValueError("Invalid catalog")
                self._catalogs[resource] = [item for item in data if isinstance(item, dict)]
            except (requests.RequestException, ValueError):
                self.log(f"Reference catalog unavailable: {resource}")
                return []
        return self._catalogs[resource]

    def get_content(self):
        data = self.Requests.fetch("custom", f"https://shared.{self.Requests.region}.a.pvp.net/content-service/v3/content", "get")
        if isinstance(data, dict) and isinstance(data.get("Seasons"), list):
            self.content = data
        return self.content

    @staticmethod
    def _seasons(content):
        seasons = content.get("Seasons") if isinstance(content, dict) else None
        return [season for season in seasons if isinstance(season, dict)] if isinstance(seasons, list) else []

    def get_latest_season_id(self, content):
        for season in self._seasons(content):
            if season.get("IsActive") and season.get("Type") == "act":
                return season.get("ID")

    def get_previous_season_id(self, content):
        seasons = self._seasons(content)
        current = next((season for season in seasons if season.get("IsActive") and season.get("Type") == "act"), {})
        if not current.get("StartTime"):
            return None
        for season in seasons:
            if current["StartTime"] == season.get("EndTime") and season.get("Type") == "act":
                return season.get("ID")
        return None

    def get_all_agents(self):
        self.agents_data = self._public_data("agents?isPlayableCharacter=true")
        agent_dict = {}
        agent_dict.update({None: None})
        agent_dict.update({"": ""})
        for agent in self.agents_data:
            if isinstance(agent.get("uuid"), str) and isinstance(agent.get("displayName"), str):
                agent_dict[agent["uuid"].lower()] = agent["displayName"]
        self.log(f"retrieved agent dict: {agent_dict}")
        return agent_dict

    def get_agent_icons(self):
        if not hasattr(self, "agents_data"):
            self.get_all_agents()
        return {
            agent["uuid"].lower(): agent.get("displayIcon")
            for agent in self.agents_data if isinstance(agent.get("uuid"), str)
        }

    def get_all_maps(self):
        """
        Requests data and assets of all maps.
        :return: JSON of all map information.
        """
        return {"data": self._public_data("maps")}

    def get_map_urls(self, maps) -> dict:
        map_dict = {}
        map_dict.update({None: None})
        for Vmap in maps["data"]:
            if isinstance(Vmap.get("mapUrl"), str) and isinstance(Vmap.get("displayName"), str):
                map_dict[Vmap["mapUrl"].lower()] = Vmap["displayName"]
        self.log(f"retrieved map dict: {map_dict}")
        return map_dict

    def get_map_splashes(self, val_maps) -> dict:
        """
        Iterates through all maps, pulling map names and splash screens.
        :param val_maps: JSON of all maps.
        :return: A dictionary of maps to splashes.
        """
        val_map_dict = {}
        val_map_dict.update({None: None})
        for val_map in val_maps["data"]:
            if isinstance(val_map.get("displayName"), str):
                val_map_dict[val_map["displayName"]] = val_map.get("splash")
        return val_map_dict

    def get_rank_icons(self):
        try:
            tier_sets = self._public_data("competitivetiers")
            latest_tiers = max(
                (tier_set.get("tiers", []) for tier_set in tier_sets),
                key=len,
                default=[],
            )
            return {
                tier["tier"]: {
                    "smallIcon": tier.get("smallIcon"),
                    "largeIcon": tier.get("largeIcon"),
                }
                for tier in latest_tiers
            }
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
            self.log("Failed to load competitive tier icons")
            return {}

    def get_act_episode_from_act_id(self, act_id):
        final = {
            "act": None,
            "episode": None
        }

        def has_letter_and_number(text):
            """Check if text contains both letters and numbers (new format)."""
            has_letter = any(c.isalpha() for c in text)
            has_number = any(c.isdigit() for c in text)
            return has_letter and has_number

        def roman_to_int(roman):
            """Convert a Roman numeral to an integer."""
            roman_values = {
                'I': 1,
                'V': 5,
                'X': 10,
                'L': 50,
                'C': 100
            }
        
            total = 0
            prev_value = 0

            for char in reversed(roman.upper()):
                if char not in roman_values:
                    return None
            
                current_value = roman_values[char]
                if current_value < prev_value:
                    total -= current_value
                else:
                    total += current_value
                prev_value = current_value

            return total

        def parse_season_number(name):
            """Parse the season number from a name string."""
            if not name or not isinstance(name, str):
                return None

            parts = name.split()
            if not parts:
                return None

            number_part = parts[-1]
            
            # If it has a letter + number(new format), return the original value.
            if has_letter_and_number(number_part):
                return number_part.lower()

            # For episodes (using regular numbers primarily)
            if name.startswith('EPISODE'):
                try:
                    return int(number_part)
                except ValueError:
                    return roman_to_int(number_part)

            # For acts (using Roman numerals primarily)
            elif name.startswith('ACT'):
                roman_result = roman_to_int(number_part)
                if roman_result is not None:
                    return roman_result
            
                try:
                    return int(number_part)
                except ValueError:
                    return None

            return None

        # Process seasons to find act and episode
        act_found = False
        seasons = self._seasons(self.content)
        if not seasons or not isinstance(act_id, str):
            return final
        episode = seasons[0]
        for season in seasons:
            # Check for matching act ID
            if str(season.get("ID", "")).lower() == act_id.lower():
                act_num = parse_season_number(season.get("Name"))
                if act_num is not None:
                    final["act"] = act_num
                act_found = True
        
            # Find the first episode after the act
            if act_found and season.get("Type") == "episode":
                episode_num = parse_season_number(episode.get("Name"))
                if episode_num is not None:
                    final["episode"] = episode_num
                break

            if season.get("Type") == "episode":
                episode = season

        return final
