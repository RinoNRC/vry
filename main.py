import asyncio
import os
import sys
import time
import traceback

import requests
import urllib3
from colr import color as colr
from InquirerPy import inquirer
from rich.console import Console as RichConsole

from src.colors import Colors
from src.config import Config
from src.configurator import configure
from src.constants import *
from src.content import Content
from src.errors import Error
from src.Loadouts import Loadouts
from src.app_state import app_state
from src.logs import Logging
from src.names import Names
from src.player_stats import PlayerStats
from src.presences import Presences
from src.rank import Rank
from src.requestsV import Requests
from src.rpc import Rpc
from src.states.coregame import Coregame
from src.states.menu import Menu
from src.states.pregame import Pregame
from src.stats import Stats
from src.table import Table
from src.websocket import Ws
from src.os_info import get_os

from src.account_manager.account_manager import AccountManager
from src.account_manager.account_config import AccountConfig
from src.account_manager.account_auth import AccountAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GUI_MODE = os.environ.get("VRY_GUI") == "1"

if not GUI_MODE:
    os.system(f"title VALORANT rank yoinker v{version}")

server = ""


def program_exit(status: int):  # so we don't need to import the entire sys module
    log(f"exited program with error code {status}")
    raise sys.exit(status)


try:
    Logging = Logging()
    log = Logging.log

    # OS Logging
    log(f"Operating system: {get_os()}\n")

    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--config":
            configure()
            run_app = inquirer.confirm(
                message="Do you want to run vRY now?", default=True
            ).execute()
            if run_app and not GUI_MODE:
                os.system("cls")
            else:
                os._exit(0)
        elif not GUI_MODE:
            os.system("cls")
    except Exception as e:
        print("Something went wrong while running configurator!")
        log(f"configurator encountered an error")
        log(str(traceback.format_exc()))
        input("press enter to exit...\n")
        os._exit(1)

    acc_manager = AccountManager(log, AccountConfig, AccountAuth, NUMBERTORANKS)

    ErrorSRC = Error(log, acc_manager, app_state)

    Requests.check_version(version, Requests.copy_run_update_script)
    Requests.check_status()
    Requests = Requests(version, log, ErrorSRC)

    cfg = Config(log)

    content = Content(Requests, log)

    rank = Rank(Requests, log, content, before_ascendant_seasons)
    pstats = PlayerStats(Requests, log, cfg)

    namesClass = Names(Requests, log)

    presences = Presences(Requests, log)

    menu = Menu(Requests, log, presences)
    pregame = Pregame(Requests, log)
    coregame = Coregame(Requests, log)

    agent_dict = content.get_all_agents()
    agent_icons = content.get_agent_icons()

    def get_display_player_name(player, names):
        if player.get("PlayerIdentity", {}).get("Incognito"):
            character_id = str(player.get("CharacterID") or "").lower()
            return agent_dict.get(character_id) or "Скрытый игрок"
        return names.get(player.get("Subject"), "Unknown")

    map_info = content.get_all_maps()
    map_urls = content.get_map_urls(map_info)
    map_splashes = content.get_map_splashes(map_info)
    rank_icons = content.get_rank_icons()

    current_map = coregame.get_current_map(map_urls, map_splashes)

    colors = Colors(log, hide_names, agent_dict, AGENTCOLORLIST)

    loadoutsClass = Loadouts(Requests, log, colors, app_state, current_map)
    table = Table(cfg, log)

    stats = Stats()

    if cfg.get_feature_flag("discord_rpc"):
        rpc = Rpc(map_urls, gamemodes, colors, log)
    else:
        rpc = None

    Wss = Ws(Requests.lockfile, Requests, cfg, colors, hide_names, app_state, rpc)
    # loop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)
    # loop.run_forever()

    log(f"VALORANT rank yoinker v{version}")

    valoApiSkins = requests.get("https://valorant-api.com/v1/weapons/skins")
    gameContent = content.get_content()
    seasonID = content.get_latest_season_id(gameContent)
    previousSeasonID = content.get_previous_season_id(gameContent)
    lastGameState = ""

    # Cache rank+stats per player for the current match so PREGAME data can be reused in INGAME
    match_player_cache = {
        "match_id": None,
        "players": {},  # puuid -> {"playerRank", "previousPlayerRank", "ppstats", "ts"}
    }
    MATCH_PLAYER_CACHE_TTL_SECONDS = 300  # safety TTL

    def reset_match_player_cache(match_id=None):
        match_player_cache["match_id"] = match_id
        match_player_cache["players"] = {}

    def ensure_match_player_cache(match_id):
        if not match_id:
            return

        # New match => reset cache
        if match_player_cache["match_id"] != match_id:
            reset_match_player_cache(match_id)
            return

        # TTL cleanup (safety)
        now = time.time()
        expired = []
        for puuid, cached in match_player_cache["players"].items():
            ts = cached.get("ts", now)
            if (now - ts) > MATCH_PLAYER_CACHE_TTL_SECONDS:
                expired.append(puuid)

        for puuid in expired:
            del match_player_cache["players"][puuid]

    def get_or_fetch_rank_and_stats(player_subject, current_match_id):
        if current_match_id:
            ensure_match_player_cache(current_match_id)
            cached = match_player_cache["players"].get(player_subject)
            if cached is not None:
                return (
                    cached["playerRank"],
                    cached["previousPlayerRank"],
                    cached["ppstats"],
                )

        # Cache miss -> fetch
        playerRank = rank.get_rank(player_subject, seasonID)
        previousPlayerRank = rank.get_rank(player_subject, previousSeasonID)
        ppstats = pstats.get_stats(player_subject)

        if current_match_id and match_player_cache["match_id"] == current_match_id:
            match_player_cache["players"][player_subject] = {
                "playerRank": dict(playerRank) if isinstance(playerRank, dict) else playerRank,
                "previousPlayerRank": dict(previousPlayerRank) if isinstance(previousPlayerRank, dict) else previousPlayerRank,
                "ppstats": dict(ppstats) if isinstance(ppstats, dict) else ppstats,
                "ts": time.time(),
            }

        return playerRank, previousPlayerRank, ppstats

    app_state.set_status("Waiting for VALORANT")

    richConsole = RichConsole()

    firstTime = True
    firstPrint = True
    while True:
        table.clear()
        table.set_default_field_names()
        table.reset_runtime_col_flags()

        # check if short ranks should be used
        if cfg.get_feature_flag("short_ranks"):
            Ranks = SHORT_NUMBERTORANKS
        else:
            Ranks = NUMBERTORANKS

        try:

            # loop = asyncio.get_event_loop()
            # loop.run_until_complete(Wss.conntect_to_websocket())
            # if firstTime:
            #     loop = asyncio.new_event_loop()
            #     asyncio.set_event_loop(loop)
            #     game_state = loop.run_until_complete(Wss.conntect_to_websocket(game_state))
            if firstTime:
                run = True
                while run:
                    presence = presences.get_presence()
                    private_presence = presences.get_private_presence(presence)
                    # wait until your own valorant presence is initialized
                    if private_presence is not None:
                        if cfg.get_feature_flag("discord_rpc"):
                            rpc.set_rpc(private_presence)
                        game_state = presences.get_game_state(presence)
                        if game_state is not None:
                            run = False
                    time.sleep(2)
                log(f"first game state: {game_state}")
            else:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                previous_game_state = game_state
                game_state = loop.run_until_complete(
                    Wss.recconect_to_websocket(game_state)
                )
                # We invalidate the cached responses when going from any state to menus
                if previous_game_state != game_state and game_state == "MENUS":
                    rank.invalidate_cached_responses()
                    reset_match_player_cache()
                    if hasattr(pstats, "clear_runtime_cache"):
                        pstats.clear_runtime_cache()
                log(f"new game state: {game_state}")
                loop.close()
            firstTime = False
            # loop = asyncio.new_event_loop()
            # asyncio.set_event_loop(loop)
            # loop.run_until_complete()
        except TypeError:
            game_state = "DISCONNECTED"
            reset_match_player_cache()
            if hasattr(pstats, "clear_runtime_cache"):
                pstats.clear_runtime_cache()

        if game_state == "DISCONNECTED":
            richConsole.print("[yellow]Disconnected from Valorant. Attempting to reconnect...[/yellow]")
            # Loop waits for the Valorant client to respond
            while True:
                # Rereads the lockfile
                Requests.lockfile = Requests.get_lockfile()

                if Requests.lockfile is None:
                    time.sleep(5)
                    continue

                presence_check = presences.get_presence()
                
                if presence_check is not None:
                    break 
                
                time.sleep(5)

            richConsole.print("[green]Reconnected successfully! Loading...[/green]")
            
            Requests.get_headers(refresh=True)

            Wss = Ws(Requests.lockfile, Requests, cfg, colors, hide_names, app_state, rpc)

            firstTime = True 
            lastGameState = ""
            reset_match_player_cache()
            if hasattr(pstats, "clear_runtime_cache"):
                pstats.clear_runtime_cache()
            continue

        if True:
            log(f"getting new {game_state} scoreboard")
            lastGameState = game_state
            game_state_dict = {
                "INGAME": color("In-Game", fore=(241, 39, 39)),
                "PREGAME": color("Agent Select", fore=(103, 237, 76)),
                "MENUS": color("In-Menus", fore=(238, 241, 54)),
            }

            if (not firstPrint) and cfg.get_feature_flag("pre_cls") and not GUI_MODE:
                os.system("cls")

            is_leaderboard_needed = False
            
            # get new presence
            presence = presences.get_presence()
            priv_presence = presences.get_private_presence(presence)
            
            # Temp fix: Riot is swapping between nested and flat API structures.
            party_state = ""
            if "partyPresenceData" in priv_presence: # Check for nested structure
                party_state = priv_presence["partyPresenceData"]["partyState"]
            elif "partyState" in priv_presence: # Check for flattened structure
                party_state = priv_presence["partyState"]
            else:
                # No known structure found, log and fail
                log("ERROR: Unknown presence API structure in 'main'.")
                party_state = priv_presence["partyPresenceData"]["partyState"]
            
            if (
                priv_presence["provisioningFlow"] == "CustomGame"
                or party_state == "CUSTOM_GAME_SETUP"
            ):
                gamemode = "Custom Game"
            else:
                gamemode = gamemodes.get(priv_presence["queueId"])

            heartbeat_data = {
                "time": int(time.time()),
                "state": game_state,
                "mode": gamemode or priv_presence.get("queueId") or "Unknown",
                "server": "",
                "region": Requests.region,
                "appVersion": version,
                "puuid": Requests.puuid,
                "players": {},
            }

            if game_state == "INGAME":
                coregame_stats = coregame.get_coregame_stats()
                if coregame_stats == None:
                    continue
                coregame_match_id = coregame.get_coregame_match_id()
                heartbeat_data["matchId"] = coregame_match_id
                ensure_match_player_cache(coregame_match_id)
                Players = coregame_stats["Players"]
                heartbeat_data["ownTeam"] = next(
                    (player.get("TeamID") for player in Players if player.get("Subject") == Requests.puuid),
                    None,
                )
                # data for chat to function
                partyMembers = menu.get_party_members(Requests.puuid, presence)
                partyMembersList = [a["Subject"] for a in partyMembers]

                players_data = {}
                players_data.update({"ignore": partyMembersList})
                for player in Players:
                    if player["Subject"] == Requests.puuid:
                        if cfg.get_feature_flag("discord_rpc"):
                            rpc.set_data({"agent": player["CharacterID"]})
                    players_data.update(
                        {
                            player["Subject"]: {
                                "team": player["TeamID"],
                                "agent": player["CharacterID"],
                                "streamer_mode": player["PlayerIdentity"]["Incognito"],
                            }
                        }
                    )
                Wss.set_player_data(players_data)

                server = coregame_stats.get("GamePodID", "")
                heartbeat_data["server"] = server
                if rpc is not None:
                    rpc.set_data({"server": server})
                presences.wait_for_presence(namesClass.get_players_puuid(Players))
                names = namesClass.get_names_from_puuids(Players)
                loadouts_arr = loadoutsClass.get_match_loadouts(
                    coregame_match_id,
                    Players,
                    cfg.weapon,
                    valoApiSkins,
                    names,
                    state="game",
                )
                loadouts = loadouts_arr[0]
                loadouts_data = loadouts_arr[1]
                # with alive_bar(total=len(Players), title='Fetching Players', bar='classic2') as bar:
                isRange = False
                playersLoaded = 1

                map_name = map_urls.get(coregame_stats["MapID"].lower(), "Unknown")
                heartbeat_data["map"] = map_name
                heartbeat_data["mapSplash"] = map_splashes.get(map_name)
                with richConsole.status("Loading Players...") as status:
                    partyOBJ = menu.get_party_json(
                        namesClass.get_players_puuid(Players), presence
                    )
                    # log(f"retrieved names dict: {names}")
                    Players.sort(
                        key=lambda Players: Players["PlayerIdentity"].get(
                            "AccountLevel"
                        ),
                        reverse=True,
                    )
                    Players.sort(key=lambda Players: Players["TeamID"], reverse=True)
                    partyCount = 0
                    partyNum = 0
                    partyIcons = {}
                    lastTeamBoolean = False
                    lastTeam = "Red"

                    already_played_with = []
                    stats_data = stats.read_data()

                    for p in Players:
                        if p["Subject"] == Requests.puuid:
                            allyTeam = p["TeamID"]
                    for player in Players:
                        status.update(
                            f"Loading players... [{playersLoaded}/{len(Players)}]"
                        )
                        playersLoaded += 1

                        if player["Subject"] in stats_data.keys():
                            if (
                                player["Subject"] != Requests.puuid
                                and player["Subject"] not in partyMembersList
                            ):
                                curr_player_stat = stats_data[player["Subject"]][-1]
                                i = 1
                                while (
                                    curr_player_stat["match_id"] == coregame.match_id
                                    and len(stats_data[player["Subject"]]) > i
                                ):
                                    i += 1
                                    # if curr_player_stat["match_id"] == coregame.match_id and len(stats_data[player["Subject"]]) > 1:
                                    curr_player_stat = stats_data[player["Subject"]][-i]
                                if curr_player_stat["match_id"] != coregame.match_id:
                                    # checking for party memebers and self players
                                    times = 0
                                    m_set = ()
                                    for m in stats_data[player["Subject"]]:
                                        if (
                                            m["match_id"] != coregame.match_id
                                            and m["match_id"] not in m_set
                                        ):
                                            times += 1
                                            m_set += (m["match_id"],)
                                    if player["PlayerIdentity"]["Incognito"] == False:
                                        already_played_with.append(
                                            {
                                                "times": times,
                                                "name": curr_player_stat["name"],
                                                "agent": curr_player_stat["agent"],
                                                "time_diff": time.time()
                                                - curr_player_stat["epoch"],
                                            }
                                        )
                                    else:
                                        if player["TeamID"] == allyTeam:
                                            team_string = "your"
                                        else:
                                            team_string = "enemy"
                                        already_played_with.append(
                                            {
                                                "times": times,
                                                "name": agent_dict.get(
                                                    player["CharacterID"].lower(), "Unknown"
                                                )
                                                + " on "
                                                + team_string
                                                + " team",
                                                "agent": curr_player_stat["agent"],
                                                "time_diff": time.time()
                                                - curr_player_stat["epoch"],
                                            }
                                        )

                        party_icon = ""
                        # set party premade icon
                        for party in partyOBJ:
                            if player["Subject"] in partyOBJ[party]:
                                if party not in partyIcons:
                                    partyIcons.update(
                                        {party: PARTYICONLIST[partyCount]}
                                    )
                                    # PARTY_ICON
                                    party_icon = PARTYICONLIST[partyCount]
                                    partyNum = partyCount + 1
                                    partyCount += 1
                                else:
                                    # PARTY_ICON
                                    party_icon = partyIcons[party]
                        playerRank, previousPlayerRank, ppstats = get_or_fetch_rank_and_stats(
                            player["Subject"], coregame_match_id
                        )

                        if player["Subject"] == Requests.puuid:
                            if cfg.get_feature_flag("discord_rpc"):
                                rpc.set_data(
                                    {
                                        "rank": playerRank["rank"],
                                        "rr": playerRank["rr"],
                                        "rank_name": colors.escape_ansi(
                                            NUMBERTORANKS[playerRank["rank"]]
                                        ),
                                    }
                                )
                        # rankStatus = playerRank[1]
                        # useless code since rate limit is handled in the requestsV
                        # while not rankStatus:
                        #     print("You have been rate limited, 😞 waiting 10 seconds!")
                        #     time.sleep(10)
                        #     playerRank = rank.get_rank(player["Subject"], seasonID)
                        #     rankStatus = playerRank[1]

                        hs = ppstats["hs"]
                        kd = ppstats["kd"]

                        rr_numeric_value = ppstats["RankedRatingEarned"]
                        afk_penalty = ppstats["AFKPenalty"]
                        ranked_rating_earned = colors.get_rr_gradient(
                            rr_numeric_value, afk_penalty
                        )

                        player_level = player["PlayerIdentity"].get("AccountLevel")

                        if player["PlayerIdentity"]["Incognito"]:
                            Namecolor = colors.get_color_from_team(
                                player["TeamID"],
                                names[player["Subject"]],
                                player["Subject"],
                                Requests.puuid,
                                agent=player["CharacterID"],
                                party_members=partyMembersList,
                            )
                        else:
                            Namecolor = colors.get_color_from_team(
                                player["TeamID"],
                                names[player["Subject"]],
                                player["Subject"],
                                Requests.puuid,
                                party_members=partyMembersList,
                            )
                        if lastTeam != player["TeamID"]:
                            if lastTeamBoolean:
                                table.add_empty_row()
                        lastTeam = player["TeamID"]
                        lastTeamBoolean = True
                        if player["PlayerIdentity"]["HideAccountLevel"]:
                            if (
                                player["Subject"] == Requests.puuid
                                or player["Subject"] in partyMembersList
                                or hide_levels == False
                            ):
                                PLcolor = colors.level_to_color(player_level)
                            else:
                                PLcolor = ""
                        else:
                            PLcolor = colors.level_to_color(player_level)
                        # AGENT
                        # agent = str(agent_dict.get(player["CharacterID"].lower()))
                        agent = colors.get_agent_from_uuid(
                            player["CharacterID"].lower()
                        )
                        if agent == "" and len(Players) == 1:
                            isRange = True

                        # NAME
                        name = Namecolor

                        # VIEWS
                        # views = get_views(names[player["Subject"]])

                        # skin
                        skin = loadouts.get(player["Subject"], "")

                        # RANK
                        rankName = Ranks[playerRank["rank"]]
                        if cfg.get_feature_flag("aggregate_rank_rr") and cfg.table.get(
                            "rr"
                        ):
                            rankName += f" ({playerRank['rr']})"

                        # RANK RATING
                        rr = playerRank["rr"]

                        # short peak rank string
                        has_letter = any(
                            c.isalpha() for c in str(playerRank["peakrankep"])
                        )
                        peakRankAct = (
                            f" ({playerRank['peakrankep']}a{playerRank['peakrankact']})"
                            if has_letter
                            else f" (e{playerRank['peakrankep']}a{playerRank['peakrankact']})"
                        )
                        if not cfg.get_feature_flag("peak_rank_act"):
                            peakRankAct = ""

                        # PEAK RANK
                        peakRank = Ranks[playerRank["peakrank"]] + peakRankAct

                        # PREVIOUS RANK
                        previousRank = Ranks[previousPlayerRank["rank"]]

                        # LEADERBOARD
                        leaderboard = playerRank["leaderboard"]

                        hs = colors.get_hs_gradient(hs)
                        wr = (
                            colors.get_wr_gradient(playerRank["wr"])
                            + f" ({playerRank['numberofgames']})"
                        )

                        if int(leaderboard) > 0:
                            is_leaderboard_needed = True

                        # LEVEL
                        level = PLcolor
                        table.add_row_table(
                            [
                                party_icon,
                                agent,
                                name,
                                # views,
                                skin,
                                rankName,
                                rr,
                                peakRank,
                                previousRank,
                                leaderboard,
                                hs,
                                wr,
                                kd,
                                level,
                                ranked_rating_earned,
                            ]
                        )

                        heartbeat_data["players"][player["Subject"]] = {
                            "puuid": player["Subject"],
                            "name": get_display_player_name(player, names),
                            "streamerMode": player["PlayerIdentity"].get("Incognito", False),
                            "partyNumber": partyNum if party_icon != "" else 0,
                             "agent": agent_dict.get(player["CharacterID"].lower(), "Unknown"),
                             "rank": playerRank["rank"],
                             "rankIcon": rank_icons.get(playerRank["rank"], {}).get("largeIcon"),
                             "previousRank": previousPlayerRank["rank"],
                             "previousRankIcon": rank_icons.get(previousPlayerRank["rank"], {}).get("largeIcon"),
                             "leaderboard": playerRank["leaderboard"],
                             "peakRank": playerRank["peakrank"],
                             "peakRankIcon": rank_icons.get(playerRank["peakrank"], {}).get("largeIcon"),
                            "peakRankAct": peakRankAct,
                             "rr": rr,
                             "earnedRR": ppstats["RankedRatingEarned"],
                             "afkPenalty": ppstats["AFKPenalty"],
                             "skin": colors.escape_ansi(skin),
                            "kd": ppstats["kd"],
                            "headshotPercentage": ppstats["hs"],
                            "winPercentage": f"{playerRank['wr']} ({playerRank['numberofgames']})",
                            "level": player_level,
                            "agentImgLink": agent_icons.get(str(player.get("CharacterID") or "").lower()),
                            "team": loadouts_data["Players"][player["Subject"]].get(
                                "Team", None
                            ),
                            "sprays": loadouts_data["Players"][player["Subject"]].get(
                                "Sprays", None
                            ),
                            "title": loadouts_data["Players"][player["Subject"]].get(
                                "Title", None
                            ),
                            "playerCard": loadouts_data["Players"][
                                player["Subject"]
                            ].get("PlayerCard", None),
                            "weapons": loadouts_data["Players"][player["Subject"]].get(
                                "Weapons", None
                            ),
                        }

                        stats.save_data(
                            {
                                player["Subject"]: {
                                    "name": names[player["Subject"]],
                                    "agent": agent_dict.get(player["CharacterID"].lower(), "Unknown"),
                                    "map": {
                                        "name": map_name,
                                        "splash": map_splashes.get(map_name),
                                    },
                                    "rank": playerRank["rank"],
                                    "rr": rr,
                                    "hs": ppstats["hs"],
                                    "kd": ppstats["kd"],
                                    "winRate": playerRank["wr"],
                                    "earnedRR": ppstats["RankedRatingEarned"],
                                    "team": player.get("TeamID"),
                                    "mode": heartbeat_data["mode"],
                                    "server": server,
                                    "account_puuid": Requests.puuid,
                                    "match_id": coregame_match_id,
                                    "epoch": time.time(),
                                }
                            }
                        )
                        # bar()
            elif game_state == "PREGAME":
                already_played_with = []
                pregame_stats = pregame.get_pregame_stats()
                if pregame_stats == None:
                    continue
                server = pregame_stats.get("GamePodID", "")
                heartbeat_data["server"] = server
                if rpc is not None:
                    rpc.set_data({"server": server})
                pregame_map_name = map_urls.get(str(pregame_stats.get("MapID", "")).lower())
                heartbeat_data["map"] = pregame_map_name
                heartbeat_data["mapSplash"] = map_splashes.get(pregame_map_name)
                Players = pregame_stats["AllyTeam"]["Players"]
                heartbeat_data["ownTeam"] = pregame_stats.get("Teams", [{}])[0].get("TeamID")
                presences.wait_for_presence(namesClass.get_players_puuid(Players))
                names = namesClass.get_names_from_puuids(Players)
                pregame_match_id = pregame_stats.get("ID")
                heartbeat_data["matchId"] = pregame_match_id
                ensure_match_player_cache(pregame_match_id)
                # temporary until other regions gets fixed?
                # loadouts = loadoutsClass.get_match_loadouts(pregame.get_pregame_match_id(), pregame_stats, cfg.weapon, valoApiSkins, names,
                #   state="pregame")
                playersLoaded = 1
                with richConsole.status("Loading Players...") as status:
                    # with alive_bar(total=len(Players), title='Fetching Players', bar='classic2') as bar:
                    presence = presences.get_presence()
                    partyOBJ = menu.get_party_json(
                        namesClass.get_players_puuid(Players), presence
                    )
                    partyMembers = menu.get_party_members(Requests.puuid, presence)
                    partyMembersList = [a["Subject"] for a in partyMembers]
                    # log(f"retrieved names dict: {names}")
                    Players.sort(
                        key=lambda Players: Players["PlayerIdentity"].get(
                            "AccountLevel"
                        ),
                        reverse=True,
                    )
                    partyCount = 0
                    partyIcons = {}
                    for player in Players:
                        status.update(
                            f"Loading players... [{playersLoaded}/{len(Players)}]"
                        )
                        playersLoaded += 1
                        party_icon = ""

                        # set party premade icon
                        for party in partyOBJ:
                            if player["Subject"] in partyOBJ[party]:
                                if party not in partyIcons:
                                    partyIcons.update(
                                        {party: PARTYICONLIST[partyCount]}
                                    )
                                    # PARTY_ICON
                                    party_icon = PARTYICONLIST[partyCount]
                                    partyNum = partyCount + 1
                                else:
                                    # PARTY_ICON
                                    party_icon = partyIcons[party]
                                partyCount += 1
                        playerRank, previousPlayerRank, ppstats = get_or_fetch_rank_and_stats(
                            player["Subject"], pregame_match_id
                        )

                        if player["Subject"] == Requests.puuid:
                            if cfg.get_feature_flag("discord_rpc"):
                                rpc.set_data(
                                    {
                                        "rank": playerRank["rank"],
                                        "rr": playerRank["rr"],
                                        "rank_name": colors.escape_ansi(
                                            NUMBERTORANKS[playerRank["rank"]]
                                        ),
                                    }
                                )
                        # rankStatus = playerRank[1]
                        # useless code since rate limit is handled in the requestsV
                        # while not rankStatus:
                        #     print("You have been rate limited, 😞 waiting 10 seconds!")
                        #     time.sleep(10)
                        #     playerRank = rank.get_rank(player["Subject"], seasonID)
                        #     rankStatus = playerRank[1]
                        # playerRank = playerRank[0]

                        hs = ppstats["hs"]
                        kd = ppstats["kd"]

                        rr_numeric_value = ppstats["RankedRatingEarned"]
                        afk_penalty = ppstats["AFKPenalty"]
                        ranked_rating_earned = colors.get_rr_gradient(
                            rr_numeric_value, afk_penalty
                        )

                        player_level = player["PlayerIdentity"].get("AccountLevel")
                        if player["PlayerIdentity"]["Incognito"]:
                            NameColor = colors.get_color_from_team(
                                pregame_stats["Teams"][0]["TeamID"],
                                names[player["Subject"]],
                                player["Subject"],
                                Requests.puuid,
                                agent=player["CharacterID"],
                                party_members=partyMembersList,
                            )
                        else:
                            NameColor = colors.get_color_from_team(
                                pregame_stats["Teams"][0]["TeamID"],
                                names[player["Subject"]],
                                player["Subject"],
                                Requests.puuid,
                                party_members=partyMembersList,
                            )

                        if player["PlayerIdentity"]["HideAccountLevel"]:
                            if (
                                player["Subject"] == Requests.puuid
                                or player["Subject"] in partyMembersList
                                or hide_levels == False
                            ):
                                PLcolor = colors.level_to_color(player_level)
                            else:
                                PLcolor = ""
                        else:
                            PLcolor = colors.level_to_color(player_level)
                        if player["CharacterSelectionState"] == "locked":
                            agent_color = color(
                                agent_dict.get(player["CharacterID"].lower(), "Unknown"),
                                fore=(255, 255, 255),
                            )
                        elif player["CharacterSelectionState"] == "selected":
                            agent_color = color(
                                agent_dict.get(player["CharacterID"].lower(), "Unknown"),
                                fore=(128, 128, 128),
                            )
                        else:
                            agent_color = color(
                                agent_dict.get(player["CharacterID"].lower(), "Unknown"),
                                fore=(54, 53, 51),
                            )

                        # AGENT
                        agent = agent_color

                        # NAME
                        name = NameColor

                        # VIEWS
                        # views = get_views(names[player["Subject"]])

                        # temporary until other regions gets fixed?
                        # skin
                        # skin = loadouts[player["Subject"]]

                        # RANK
                        rankName = Ranks[playerRank["rank"]]
                        if cfg.get_feature_flag("aggregate_rank_rr") and cfg.table.get(
                            "rr"
                        ):
                            rankName += f" ({playerRank['rr']})"

                        # RANK RATING
                        rr = playerRank["rr"]

                        # short peak rank string
                        has_letter = any(
                            c.isalpha() for c in str(playerRank["peakrankep"])
                        )
                        peakRankAct = (
                            f" ({playerRank['peakrankep']}a{playerRank['peakrankact']})"
                            if has_letter
                            else f" (e{playerRank['peakrankep']}a{playerRank['peakrankact']})"
                        )
                        if not cfg.get_feature_flag("peak_rank_act"):
                            peakRankAct = ""
                        # PEAK RANK
                        peakRank = Ranks[playerRank["peakrank"]] + peakRankAct

                        # PREVIOUS RANK
                        previousRank = Ranks[previousPlayerRank["rank"]]

                        # LEADERBOARD
                        leaderboard = playerRank["leaderboard"]

                        hs = colors.get_hs_gradient(hs)
                        wr = (
                            colors.get_wr_gradient(playerRank["wr"])
                            + f" ({playerRank['numberofgames']})"
                        )

                        if int(leaderboard) > 0:
                            is_leaderboard_needed = True

                        # LEVEL
                        level = PLcolor

                        table.add_row_table(
                            [
                                party_icon,
                                agent,
                                name,
                                # views,
                                "",
                                rankName,
                                rr,
                                peakRank,
                                previousRank,
                                leaderboard,
                                hs,
                                wr,
                                kd,
                                level,
                                ranked_rating_earned,
                            ]
                        )

                        heartbeat_data["players"][player["Subject"]] = {
                            "puuid": player["Subject"],
                            "name": get_display_player_name(player, names),
                            "streamerMode": player["PlayerIdentity"].get("Incognito", False),
                            "team": heartbeat_data.get("ownTeam"),
                            "partyNumber": partyNum if party_icon != "" else 0,
                            "agent": agent_dict.get(player["CharacterID"].lower(), "Unknown"),
                            "agentImgLink": agent_icons.get(str(player.get("CharacterID") or "").lower()),
                            "rank": playerRank["rank"],
                            "rankIcon": rank_icons.get(playerRank["rank"], {}).get("largeIcon"),
                            "previousRank": previousPlayerRank["rank"],
                            "previousRankIcon": rank_icons.get(previousPlayerRank["rank"], {}).get("largeIcon"),
                            "leaderboard": playerRank["leaderboard"],
                            "peakRank": playerRank["peakrank"],
                            "peakRankIcon": rank_icons.get(playerRank["peakrank"], {}).get("largeIcon"),
                            "peakRankAct": peakRankAct,
                            "level": player_level,
                            "rr": rr,
                            "earnedRR": ppstats["RankedRatingEarned"],
                            "afkPenalty": ppstats["AFKPenalty"],
                            "kd": ppstats["kd"],
                            "headshotPercentage": ppstats["hs"],
                            "winPercentage": f"{playerRank['wr']} ({playerRank['numberofgames']})",
                        }

                        # bar()
            if game_state == "MENUS":
                reset_match_player_cache()
                if hasattr(pstats, "clear_runtime_cache"):
                    pstats.clear_runtime_cache()

                server = ""
                already_played_with = []
                Players = menu.get_party_members(Requests.puuid, presence)
                names = namesClass.get_names_from_puuids(Players)
                playersLoaded = 1
                with richConsole.status("Loading Players...") as status:
                    # with alive_bar(total=len(Players), title='Fetching Players', bar='classic2') as bar:
                    # log(f"retrieved names dict: {names}")
                    Players.sort(
                        key=lambda Players: Players["PlayerIdentity"].get(
                            "AccountLevel"
                        ),
                        reverse=True,
                    )
                    seen = []
                    for player in Players:

                        if player not in seen:
                            status.update(
                                f"Loading players... [{playersLoaded}/{len(Players)}]"
                            )
                            playersLoaded += 1
                            party_icon = PARTYICONLIST[0]
                            playerRank = rank.get_rank(player["Subject"], seasonID)
                            previousPlayerRank = rank.get_rank(
                                player["Subject"], previousSeasonID
                            )
                            if player["Subject"] == Requests.puuid:
                                if cfg.get_feature_flag("discord_rpc"):
                                    rpc.set_data(
                                        {
                                        "rank": playerRank["rank"],
                                        "rr": playerRank["rr"],
                                        "rank_name": colors.escape_ansi(
                                            NUMBERTORANKS[playerRank["rank"]]
                                        ),
                                        }
                                    )

                            # rankStatus = playerRank[1]
                            # useless code since rate limit is handled in the requestsV
                            # while not rankStatus:
                            #     print("You have been rate limited, 😞 waiting 10 seconds!")
                            #     time.sleep(10)
                            #     playerRank = rank.get_rank(player["Subject"], seasonID)
                            #     rankStatus = playerRank[1]
                            # playerRank = playerRank["rank"]

                            ppstats = pstats.get_stats(player["Subject"])
                            hs = ppstats["hs"]
                            kd = ppstats["kd"]

                            rr_numeric_value = ppstats["RankedRatingEarned"]
                            afk_penalty = ppstats["AFKPenalty"]
                            ranked_rating_earned = colors.get_rr_gradient(
                                rr_numeric_value, afk_penalty
                            )

                            player_level = player["PlayerIdentity"].get("AccountLevel")
                            PLcolor = colors.level_to_color(player_level)

                            # AGENT
                            agent = ""

                            # NAME
                            name = color(names[player["Subject"]], fore=(76, 151, 237))

                            # RANK
                            rankName = Ranks[playerRank["rank"]]
                            if cfg.get_feature_flag(
                                "aggregate_rank_rr"
                            ) and cfg.table.get("rr"):
                                rankName += f" ({playerRank['rr']})"

                            # RANK RATING
                            rr = playerRank["rr"]

                            # short peak rank string
                            has_letter = any(
                                c.isalpha() for c in str(playerRank["peakrankep"])
                            )
                            peakRankAct = (
                                f" ({playerRank['peakrankep']}a{playerRank['peakrankact']})"
                                if has_letter
                                else f" (e{playerRank['peakrankep']}a{playerRank['peakrankact']})"
                            )
                            if not cfg.get_feature_flag("peak_rank_act"):
                                peakRankAct = ""

                            # PEAK RANK
                            peakRank = (
                                Ranks[playerRank["peakrank"]] + peakRankAct
                            )

                            # PREVIOUS RANK
                            previousRank = Ranks[previousPlayerRank["rank"]]

                            # LEADERBOARD
                            leaderboard = playerRank["leaderboard"]

                            hs = colors.get_hs_gradient(hs)
                            wr = (
                                colors.get_wr_gradient(playerRank["wr"])
                                + f" ({playerRank['numberofgames']})"
                            )

                            if int(leaderboard) > 0:
                                is_leaderboard_needed = True

                            # LEVEL
                            level = PLcolor

                            table.add_row_table(
                                [
                                    party_icon,
                                    agent,
                                    name,
                                    "",
                                    rankName,
                                    rr,
                                    peakRank,
                                    previousRank,
                                    leaderboard,
                                    hs,
                                    wr,
                                    kd,
                                    level,
                                    ranked_rating_earned,
                                ]
                            )

                            heartbeat_data["players"][player["Subject"]] = {
                                "puuid": player["Subject"],
                                "name": get_display_player_name(player, names),
                                "streamerMode": player["PlayerIdentity"].get("Incognito", False),
                                "team": heartbeat_data.get("ownTeam"),
                                "agentImgLink": agent_icons.get(str(player.get("CharacterID") or "").lower()),
                                "rank": playerRank["rank"],
                                "rankIcon": rank_icons.get(playerRank["rank"], {}).get("largeIcon"),
                                "previousRank": previousPlayerRank["rank"],
                                "previousRankIcon": rank_icons.get(previousPlayerRank["rank"], {}).get("largeIcon"),
                                "leaderboard": playerRank["leaderboard"],
                                "peakRank": playerRank["peakrank"],
                                "peakRankIcon": rank_icons.get(playerRank["peakrank"], {}).get("largeIcon"),
                                "peakRankAct": peakRankAct,
                                "level": player_level,
                                "rr": rr,
                                "earnedRR": ppstats["RankedRatingEarned"],
                                "afkPenalty": ppstats["AFKPenalty"],
                                "kd": ppstats["kd"],
                                "headshotPercentage": ppstats["hs"],
                                "winPercentage": f"{playerRank['wr']} ({playerRank['numberofgames']})",
                            }

                            # bar()
                    seen.append(player["Subject"])
            if (title := game_state_dict.get(game_state)) is None:
                # program_exit(1)
                time.sleep(9)
            
            title_parts = [f"VALORANT status: {title}"]

            if cfg.get_feature_flag("server_id") and server != "":
                parts = server.split('.')
                if len(parts) > 2:
                    short_serverID = '.'.join(parts[2:])
                else:
                    short_serverID = server
                title_parts.append(f" {colr('- ' + short_serverID, fore=(200, 200, 200))}")
            
            table.set_title(''.join(title_parts))
            
            if title is not None:
                if cfg.get_feature_flag("auto_hide_leaderboard") and (
                    not is_leaderboard_needed
                ):
                    table.set_runtime_col_flag("Pos.", False)

                if game_state == "MENUS":
                    table.set_runtime_col_flag("Party", False)
                    table.set_runtime_col_flag("Agent", False)
                    table.set_runtime_col_flag(cfg.weapon.capitalize(), False)

                if game_state == "INGAME":
                    if isRange:
                        table.set_runtime_col_flag("Party", False)
                        table.set_runtime_col_flag("Agent", False)

                # We don't to show the RR column if the "aggregate_rank_rr" feature flag is True.
                table.set_runtime_col_flag(
                    "RR",
                    cfg.table.get("rr")
                    and not cfg.get_feature_flag("aggregate_rank_rr"),
                )

                table.set_caption(f"VALORANT rank yoinker v{version}")
                app_state.publish("heartbeat", heartbeat_data)
                table.display()
                firstPrint = False

                # print(f"VALORANT rank yoinker v{version}")
                if cfg.get_feature_flag("last_played"):
                    if len(already_played_with) > 0:
                        print("\n")
                        for played in already_played_with:
                            print(
                                f"Already played with {played['name']} (last {played['agent']}) {stats.convert_time(played['time_diff'])} ago. (Total played {played['times']} times)"
                            )
                already_played_with = []
        if cfg.cooldown == 0 and os.environ.get("VRY_GUI") != "1":
            input("Press enter to fetch again...")
        else:
            # time.sleep(cfg.cooldown)
            pass
except KeyboardInterrupt:
    # lame implementation of fast ctrl+c exit
    os._exit(0)
except:
    log(traceback.format_exc())
    app_state.set_error(traceback.format_exc())
    print(
        color(
            "The program has encountered an error. If the problem persists, please reach support"
            f" with the logs found in {os.getcwd()}\\logs",
            fore=(255, 0, 0),
        )
    )
    if os.environ.get("VRY_GUI") != "1":
        input("press enter to exit...\n")
        os._exit(1)
