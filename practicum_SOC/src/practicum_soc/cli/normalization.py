"""Argumentos CLI; utiliza funciones independientes del motor."""

import argparse
import json
from pathlib import Path

from practicum_soc.soc.normalization import NormalizationConfig, _read_secret, normalize_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rejected-output", type=Path, required=True)
    parser.add_argument("--stats-output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/normalization.json"))
    parser.add_argument("--pseudonym-key-env", default="SOC_PSEUDONYM_KEY")
    parser.add_argument("--pseudonym-key-file", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    result = normalize_csv(
        input_csv=args.input_csv,
        normalized_output=args.output,
        rejected_output=args.rejected_output,
        stats_output=args.stats_output,
        secret=_read_secret(args.pseudonym_key_file, args.pseudonym_key_env),
        config=NormalizationConfig.from_file(args.config),
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
