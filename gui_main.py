import os
import sys
import threading
import traceback

from src.app_state import app_state
from src.gui import run_gui


def run_monitor():
    try:
        import main  # noqa: F401 - importing starts the legacy monitor loop
    except SystemExit as exc:
        if exc.code not in (None, 0):
            app_state.set_error(f"Monitor stopped with exit code {exc.code}")
    except Exception:
        app_state.set_error(traceback.format_exc())


if __name__ == "__main__":
    os.environ["VRY_GUI"] = "1"
    null_stream = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = null_stream
    sys.stderr = null_stream
    app_state.set_status("Connecting")
    threading.Thread(target=run_monitor, name="riot-monitor", daemon=True).start()
    run_gui()
