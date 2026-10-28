"""Run the engine on your own machine for a demo: demo mode, port 8000, auto-reload.

The same command works in PowerShell, cmd, Git Bash and macOS/Linux shells,
because no environment variable has to be set in the shell first:

    .venv/Scripts/python engine/run_local.py      (Windows, from the Canonry folder)
    .venv/bin/python engine/run_local.py          (macOS / Linux)

Settings already in the environment win (e.g. PORT=8010, or CANONRY_DEMO_MODE=false).
Deployments do not use this file; they start uvicorn directly (engine/Dockerfile).
"""
import os

import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    os.environ.setdefault("CANONRY_DEMO_MODE", "true")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Canonry engine (demo mode={os.environ['CANONRY_DEMO_MODE']}) on http://127.0.0.1:{port}")
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True, app_dir=HERE, reload_dirs=[HERE])


if __name__ == "__main__":
    main()
