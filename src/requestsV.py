import base64
import time
import requests
from colr import color
import os
import shutil
import sys
import zipfile
import io
import subprocess

class Requests:
    def __init__(self, version, log, Error):
        self.Error = Error
        self.version = version
        self.headers = {}
        self.log = log


        self.lockfile = self.get_lockfile()
        self.region = self.get_region()
        self.pd_url = f"https://pd.{self.region[0]}.a.pvp.net"
        self.glz_url = f"https://glz-{self.region[1][0]}.{self.region[1][1]}.a.pvp.net"
        self.log(f"Api urls: pd_url: '{self.pd_url}', glz_url: '{self.glz_url}'")
        self.region = self.region[0]
        
        self.puuid = ''
        #fetch puuid so its avaible outside
        if not self.get_headers(init=True):
            self.log("Invalid URI format, invalid lockfile, going back to menu")
            self.get_lockfile(ignoreLockfile=True)
        

    @staticmethod
    def check_version(version, copy_run_update_script):
        if os.getenv("VRY_GUI") == "1":
            return
        # checking for latest release
        try:
            r = requests.get("https://api.github.com/repos/zayKenyon/VALORANT-rank-yoinker/releases", timeout=(3, 10))
        except requests.exceptions.RequestException:
            print(color("[WARNING] Unable to check for updates - skipping...", fore=(255, 165, 0)))
            return

        try:
            json_data = r.json()
            release_version = json_data[0]["tag_name"]  # get release version
            for asset in json_data[0]["assets"]:
                if "zip" in asset["content_type"]:
                        link = asset["browser_download_url"] # link for the latest release
                        break
            if float(release_version) > float(version):
                print(color("[UPDATE] New version available!", fore=(0, 255, 0)))
                if sys.argv[0][-3:] == "exe":
                    while True:
                        update_now = input(color("Would you like to update now? (Y/n): ", fore=(0, 255, 0)))
                        if update_now.lower() == "n" or update_now.lower() == "no":
                            return
                        elif update_now.lower() == "y" or update_now.lower() == "yes" or update_now == "":
                            copy_run_update_script(link)
                            os._exit(1)
                        else:
                            print('Please respond with "yes" or "no" ("y", "n") or press enter')
        except Exception:
            print(color("[WARNING] Error checking for updates - skipping...", fore=(255, 165, 0)))
            return

    @staticmethod
    def copy_run_update_script(link):
        if os.getenv("VRY_GUI") == "1":
            return
        try:
            os.mkdir(os.path.join(os.getenv('APPDATA'), "vry"))
        except FileExistsError:
            pass
        shutil.copyfile("updatescript.bat", os.path.join(os.getenv('APPDATA'), "vry", "updatescript.bat"))
        r_zip = requests.get(link, stream=True, timeout=(3, 30))
        r_zip.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r_zip.content))
        z.extractall(os.path.join(os.getenv('APPDATA'), "vry"))
        subprocess.Popen([os.path.join(os.getenv('APPDATA'), "vry", "updatescript.bat"), os.path.join(os.getenv('APPDATA'), "vry", ".".join(os.path.basename(link).split(".")[:-1])), os.getcwd(), os.path.join(os.getenv('APPDATA'), "vry")])

    @staticmethod
    def check_status():
        if os.getenv("VRY_GUI") == "1":
            return
        # checking status
        try:
            rStatus = requests.get(
                "https://raw.githubusercontent.com/zayKenyon/VALORANT-rank-yoinker/main/status.json", timeout=(3, 10))
        except requests.exceptions.RequestException:
            print(color("[WARNING] Unable to check status - skipping...", fore=(255, 165, 0)))
            return

        try:
            status_data = rStatus.json()
            if not status_data["status_good"] or status_data["print_message"]:
                status_color = (255, 0, 0) if not status_data["status_good"] else (0, 255, 0)
                print(color(status_data["message_to_display"], fore=status_color))
        except Exception:
            print(color("[WARNING] Failed processing status - skipping...", fore=(255, 165, 0)))
            return
            
    @staticmethod
    def _payload(response):
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, (dict, list)) else None

    @staticmethod
    def _valid_lockfile(lockfile):
        if not isinstance(lockfile, dict):
            return False
        port = lockfile.get('port')
        password = lockfile.get('password')
        if isinstance(port, bool) or not isinstance(port, (str, int)):
            return False
        if not str(port).isascii() or not str(port).isdigit() or len(str(port)) > 5:
            return False
        if not 1 <= int(port) <= 65535:
            return False
        return isinstance(password, str) and bool(password) and not any(c in password for c in ':\r\n')

    def _local_headers(self):
        if not self._valid_lockfile(self.lockfile):
            return None
        return {'Authorization': 'Basic ' + base64.b64encode(('riot:' + self.lockfile['password']).encode()).decode()}

    def fetch(self, url_type: str, endpoint: str, method: str, rate_limit_seconds=5, json=None):
        request_kwargs = {} if json is None else {"json": json}
        if url_type == "local":
            local_headers = self._local_headers()
            if local_headers is None:
                self.log("Invalid lockfile for local request.")
                return None
            for attempt in range(3):
                try:
                    response = requests.request(
                        method, f"https://127.0.0.1:{self.lockfile['port']}{endpoint}",
                        headers=local_headers, verify=False, timeout=5, **request_kwargs)
                except requests.exceptions.RequestException:
                    self.log("Connection error on local request.")
                else:
                    payload = self._payload(response)
                    rpc_error = isinstance(payload, dict) and payload.get("errorCode") == "RPC_ERROR"
                    if response.status_code == 200 and payload is not None and not rpc_error:
                        return payload
                    self.log(f"Local request failed, response code: {response.status_code}")
                    if response.status_code in {401, 403, 404}:
                        return None
                    if response.status_code != 200 and response.status_code != 429 and response.status_code < 500:
                        return None
                if attempt < 2:
                    time.sleep(1)
            return None

        if url_type not in {"pd", "glz", "custom"}:
            return None
        url = endpoint if url_type == "custom" else (
            self.pd_url if url_type == "pd" else self.glz_url) + endpoint
        headers = self.get_headers()
        if not headers:
            return None
        for attempt in range(2):
            try:
                response = requests.request(
                    method, url, headers=headers, verify=True, timeout=(3, 7), **request_kwargs)
            except requests.exceptions.RequestException:
                self.log(f"Connection error on {url_type} request.")
                if attempt == 0:
                    time.sleep(min(max(rate_limit_seconds, 1), 5))
                    continue
                return None
            self.log(f"fetch: url: '{url_type}', method: {method}, response code: {response.status_code}")
            payload = self._payload(response)
            result = response if url_type == "pd" else payload
            if response.status_code in {403, 404}:
                return result
            bad_claims = isinstance(payload, dict) and payload.get("errorCode") == "BAD_CLAIMS"
            if response.status_code == 401 or bad_claims:
                if attempt == 0:
                    headers = self.get_headers(refresh=True)
                    if headers:
                        continue
                return result
            if attempt == 0 and (response.status_code == 429 or response.status_code >= 500):
                time.sleep(min(max(rate_limit_seconds, 1), 5))
                continue
            return result
        return None

    def get_region(self):
        path = os.path.join(os.getenv('LOCALAPPDATA'), R'VALORANT\Saved\Logs\ShooterGame.log')
        with open(path, "r", encoding="utf8") as file:
            while True:
                line = file.readline()
                if not line:
                    raise RuntimeError("Could not find Riot API region in ShooterGame.log")
                if '.a.pvp.net/account-xp/v1/' in line:
                    pd_url = line.split('.a.pvp.net/account-xp/v1/')[0].split('.')[-1]
                elif 'https://glz' in line:
                    glz_url = [(line.split('https://glz-')[1].split(".")[0]),
                               (line.split('https://glz-')[1].split(".")[1])]
                if "pd_url" in locals().keys() and "glz_url" in locals().keys():
                    self.log(f"got region from logs '{[pd_url, glz_url]}'")
                    if pd_url == "pbe":
                        return ["na", ["na-1", "na"]]
                    return [pd_url, glz_url]

    def get_current_version(self):
        path = os.path.join(os.getenv('LOCALAPPDATA'), R'VALORANT\Saved\Logs\ShooterGame.log')
        with open(path, "r", encoding="utf8") as file:
            while True:
                line = file.readline()
                if not line:
                    raise RuntimeError("Could not find CI server version in ShooterGame.log")
                if 'CI server version:' in line:
                    version_without_shipping = line.split('CI server version: ')[1].strip()
                    version = version_without_shipping.split("-")
                    version = "-".join(version)
                    self.log(f"got version from logs '{version}'")
                    return version

    def get_lockfile(self, ignoreLockfile=False):
        #ignoring lockfile is for when lockfile exists but it's not really valid, (local endpoints are not initialized yet)
        path = os.path.join(os.getenv('LOCALAPPDATA'), R'Riot Games\Riot Client\Config\lockfile')
        
        if self.Error.LockfileError(path, ignoreLockfile=ignoreLockfile):
            with open(path) as lockfile:
                self.log("opened lockfile")
                data = lockfile.read().strip().split(':')
                keys = ['name', 'PID', 'port', 'password', 'protocol']
                if len(data) == len(keys):
                    parsed = dict(zip(keys, data))
                    if self._valid_lockfile(parsed):
                        return parsed
                self.log("Invalid lockfile structure.")
                return None


    def get_headers(self, refresh=False, init=False):
        if self.headers and not refresh:
            return self.headers
        local_headers = self._local_headers()
        if local_headers is None:
            self.log("Invalid lockfile for entitlement request.")
            return False if init else None
        max_attempts = 30 if init else 3
        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    f"https://127.0.0.1:{self.lockfile['port']}/entitlements/v1/token",
                    headers=local_headers, verify=False, timeout=5)
            except requests.exceptions.RequestException:
                self.log("Connection error while fetching Riot Client entitlement token.")
            else:
                entitlements = self._payload(response)
                if response.status_code in {401, 403, 404}:
                    break
                if isinstance(entitlements, dict) and entitlements.get("message") == "Invalid URI format":
                    self.log("Invalid URI format while fetching entitlement token.")
                    break
                if response.ok and isinstance(entitlements, dict) and all(
                        isinstance(entitlements.get(key), str) and entitlements[key].strip()
                        and not any(c in entitlements[key] for c in '\r\n')
                        for key in ('subject', 'accessToken', 'token')):
                    try:
                        version = self.get_current_version()
                    except (OSError, RuntimeError, ValueError):
                        self.log("Unable to read Riot Client version.")
                        break
                    headers = {
                        'Authorization': f"Bearer {entitlements['accessToken']}",
                        'X-Riot-Entitlements-JWT': entitlements['token'],
                        'X-Riot-ClientPlatform': "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjog"
                                                 "IldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5"
                                                 "MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9",
                        'X-Riot-ClientVersion': version,
                        "User-Agent": "ShooterGame/13 Windows/10.0.19043.1.256.64bit"
                    }
                    self.puuid = entitlements['subject']
                    self.headers = headers
                    self.log("Fetched Riot Client entitlement token.")
                    return headers
                self.log(f"Entitlement token unavailable, response code: {response.status_code}")
                if response.status_code != 200 and response.status_code != 429 and response.status_code < 500:
                    break
            if attempt < max_attempts - 1:
                time.sleep(1)
        self.log("Riot Client did not provide an entitlement token.")
        return False if init else None
