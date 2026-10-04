"""Argumentos CLI; utiliza funciones independientes del motor."""

import argparse
import json
from pathlib import Path

from practicum_soc.soc.detection import (
    detect_alerts,
    evaluation_events,
    load_baseline_context,
    load_events,
    write_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/detection_rules.json"))
    parser.add_argument("--baseline-dir", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    baseline = load_baseline_context(args.baseline_dir)
    all_events, skipped = load_events(args.input_csv, config["timezone"])
    events = evaluation_events(all_events, baseline)
    alerts = detect_alerts(events, config, baseline)
    summary = write_outputs(
        alerts,
        args.output_dir,
        {
            "source_file": str(args.input_csv),
            "timezone": config["timezone"],
            "processed_events": len(events),
            "training_events_excluded": len(all_events) - len(events),
            "skipped_invalid_time": skipped,
            "rules_are_provisional": True,
            "human_review_required": True,
        },
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
