"""Worker durable independiente del proceso web; no inicia análisis por sí solo."""

import argparse
import logging
import os
import time
from pathlib import Path

from practicum_soc.core.config import load_env_file
from practicum_soc.core.investigation_config import InvestigationSettings, InvestigationUnavailable
from practicum_soc.core.paths import PROJECT_ROOT
from practicum_soc.services.investigation import InvestigationWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--state-db", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    load_env_file(args.env_file)
    logging.basicConfig(level=logging.INFO)
    try:
        policy = InvestigationSettings.load()
        policy.require_available()
        state_db = args.state_db or Path(
            os.environ.get("SOC_STATE_DB", str(PROJECT_ROOT / "analysis/state/soc_alerts.db"))
        )
        worker = InvestigationWorker(state_db)
        while True:
            try:
                identifier = worker.run_once(policy)
                if identifier:
                    logging.info("Trabajo de investigación procesado: %s", identifier)
            except Exception as error:
                logging.error("Worker no disponible: %s", type(error).__name__)
            if args.once:
                break
            time.sleep(policy.poll_seconds)
    except KeyboardInterrupt:
        return
    except InvestigationUnavailable as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit(
            f"No se pudo iniciar el worker: {type(error).__name__}; revise configuración"
        ) from None


if __name__ == "__main__":
    main()
