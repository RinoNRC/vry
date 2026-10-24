import sys
from pathlib import Path
from cx_Freeze import setup, Executable
from src.constants import version

# with open("requirements.txt", "r") as f:
#     requirements = f.read().splitlines()
#     packages = []
#     for r in requirements:
#         if "==" in r:
#             packages.append(r.split("==")[0])
#         elif "~=" in r:
#             packages.append(r.split("~=")[0])
#         elif ">=" in r:
#             packages.append(r.split(">=")[0])
#         elif "<=" in r:
#             packages.append(r.split("<=")[0])

build_exe_options = {
    "path": sys.path,
    "include_files":['configurator.bat', 'updatescript.bat', 'assets', 'LICENSE', 'config.example.json'],
    "includes": ["main"],
    "packages": ["requests", "colr", "flet", "flet_desktop", "winotify", "InquirerPy", "websockets", "pypresence", "nest_asyncio", "rich"],
    "excludes": ["tkinter", "test", "unittest", "xmlrpc"]
}

setup(
    name = "VALORANT rank yoinker",
    version = version,
    description='vRY - VALORANT rank yoinker',
    executables = [Executable("gui_main.py", icon="./assets/Logo.ico" if Path("assets/Logo.ico").exists() else None, target_name="vry.exe", base="gui", copyright="RinoNRC", trademarks="VALORANT is a trademark of Riot Games")],
    options={"build_exe": build_exe_options}
)
