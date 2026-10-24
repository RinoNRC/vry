import os
import sys
import threading
import traceback
from pathlib import Path

from src.app_state import app_state
from src.gui import run_gui


def run_monitor():
    try:
        import main  # noqa: F401 - importing starts the legacy monitor loop
    except SystemExit as exc:
        if exc.code not in (None, 0):
            app_state.set_error(f"Monitor stopped with exit code {exc.code}")
    except Exception:
        error_log = Path(__file__).resolve().parent / "logs" / "gui-error.log"
        error_log.parent.mkdir(exist_ok=True)
        error = traceback.format_exc()
        with error_log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n{'=' * 72}\n{error}\n")
        app_state.set_error("Ошибка монитора. Подробности записаны в logs/gui-error.log")


if __name__ == "__main__":
    os.environ["VRY_GUI"] = "1"
    null_stream = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = null_stream
    sys.stderr = null_stream
    app_state.set_status("Connecting")
    threading.Thread(target=run_monitor, name="riot-monitor", daemon=True).start()
    try:
        run_gui()
    except Exception:
        error_log = Path(__file__).resolve().parent / "logs" / "gui-error.log"
        error_log.parent.mkdir(exist_ok=True)
        with error_log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n{'=' * 72}\nGUI startup failed\n{traceback.format_exc()}\n")
        raise
