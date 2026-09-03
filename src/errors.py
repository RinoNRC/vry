import socket
import json
import os.path
import time
import os

from src.constants import DEFAULT_CONFIG

class Error:
    
    def __init__(self, log, acc_manager, state_store=None):
        self.log = log
        self.acc_manager = acc_manager
        self.state_store = state_store

    def auto_launch_enabled(self):
        try:
            with open("config.json", "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            return bool(config.get("flags", {}).get("auto_launch_valorant", False))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_CONFIG["flags"]["auto_launch_valorant"]

    def PortError(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        except:
            print("""vRY is being blocked by the firewall!!
            - Check your firewall settings and whitelist the program / disable firewall
            - Try Restarting vRY and/or VALORANT, if non works try restarting your computer
            - If you have a slower internet connection, changing the value of cooldown located in config.json to 0 or any number greater than 1 may help.
            - If that doesn't work then changing the port number located in config.json file may work.
            - If all the above mentioned steps does not work, please join the support server!. 
            """)
            self.log("Port is being blocked by the firewall or in use by another application")
        sock.close()

    def LockfileError(self, path, ignoreLockfile=False):
        #ignoring lockfile is for when lockfile exists but it's not really valid, (local endpoints are not initialized yet)
        if os.path.exists(path) and ignoreLockfile == False:
            return True
        else:
            self.log("Lockfile does not exist, VALORANT is not open")
            if self.state_store:
                self.state_store.set_status("Waiting for VALORANT")
            launched = False
            while not os.path.exists(path):
                if not launched and self.auto_launch_enabled():
                    self.log("Auto-launch enabled, starting VALORANT")
                    if self.state_store:
                        self.state_store.set_status("Launching VALORANT")
                    self.acc_manager.start_valorant()
                    launched = True
                time.sleep(1)
            if self.state_store:
                self.state_store.set_status("Connecting")
            if os.environ.get("VRY_GUI") != "1":
                os.system('cls')
            return True
