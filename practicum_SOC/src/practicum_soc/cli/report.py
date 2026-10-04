"""Argumentos CLI; utiliza funciones independientes del motor."""

import argparse
import json
from pathlib import Path

from practicum_soc.analytics.reporting import generate_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-dir", type=Path, default=Path("analysis"))
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/report"))
    parser.add_argument(
        "--detection-config", type=Path, default=Path("config/detection_rules.json")
    )
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--source-name", default="csv_demo_mvp")
    args = parser.parse_args()
    report = generate_report(
        args.analysis_dir,
        args.output_dir,
        detection_config_path=args.detection_config,
        state_db=args.state_db,
        source_name=args.source_name,
    )
    print(json.dumps({"report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
