"""Run the app as a single process: the server plus the built UI, and open the browser.

Also runs without a window (pythonw); the log is written to logs/server.log.
  --reload      restart the server automatically when a .py or .env file changes (dev mode)
  --no-browser  do not open a browser
"""
import os
import socket
import sys
import threading
import webbrowser

BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
PORT = int(os.getenv("TRACKER_PORT", "8000"))
URL = f"http://localhost:{PORT}"


def already_running():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main():
    if already_running():
        webbrowser.open(URL)  # already running: just open the browser
        return

    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # pythonw: there is no console
        log = open(os.path.join(ROOT, "logs", "server.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    import uvicorn

    if "--no-browser" not in sys.argv:
        threading.Timer(2.0, lambda: webbrowser.open(URL)).start()
    if "--reload" in sys.argv:
        # On Windows the reload process re-imports this file, which is why everything sits under if __name__ == "__main__"
        uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="info", reload=True,
                    reload_dirs=[BACKEND], reload_includes=["*.py", ".env"], reload_excludes=[".venv/*"])
    else:
        from app.main import app
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
