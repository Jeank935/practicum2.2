"""Arranque compatible de herramientas: importa el paquete desde su carpeta src."""

import os
import subprocess
import sys
from pathlib import Path


def run_backend_cli(module: str) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    paths = [str(root / "src"), environment.get("PYTHONPATH", "")]
    environment["PYTHONPATH"] = os.pathsep.join(path for path in paths if path)
    result = subprocess.run(
        [sys.executable, "-m", module, *sys.argv[1:]], env=environment, check=False
    )
    raise SystemExit(result.returncode)
