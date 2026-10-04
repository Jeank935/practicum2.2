"""Argumentos CLI; utiliza funciones independientes del motor."""

import argparse
import json
from pathlib import Path

from practicum_soc.soc.baseline import run_baseline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/baseline.json"))
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    summary = run_baseline(args.input_csv, args.output_dir, config)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
