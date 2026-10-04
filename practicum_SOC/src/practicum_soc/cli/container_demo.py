"""Pipeline histórico portable: usa los mismos módulos que run_analysis.ps1."""

from pathlib import Path

from practicum_soc.core.config import load_json, read_pseudonym_secret
from practicum_soc.services.dashboard import DashboardService
from practicum_soc.soc.baseline import run_baseline
from practicum_soc.soc.detection import (
    detect_alerts,
    evaluation_events,
    load_baseline_context,
    load_events,
    write_outputs,
)
from practicum_soc.soc.normalization import NormalizationConfig, normalize_csv


def run_pipeline(input_csv: Path, analysis: Path, config: Path = Path("config")) -> dict:
    normalize_csv(
        input_csv=input_csv,
        normalized_output=analysis / "normalized_events.csv",
        rejected_output=analysis / "rejected_events.csv",
        stats_output=analysis / "normalization_stats.json",
        secret=read_pseudonym_secret(None),
        config=NormalizationConfig.from_file(config / "normalization.json"),
    )
    run_baseline(
        analysis / "normalized_events.csv",
        analysis / "baseline",
        load_json(config / "baseline.json"),
    )
    service = DashboardService(
        state_db=analysis / "state/soc_alerts.db",
        analysis_dir=analysis,
        detection_config=config / "detection_rules.json",
        operational_config=config / "operational.json",
    )
    rules = load_json(config / "detection_rules.json")
    baseline = load_baseline_context(analysis / "baseline")
    all_events, skipped = load_events(analysis / "normalized_events.csv", rules["timezone"])
    events = evaluation_events(all_events, baseline)
    write_outputs(
        detect_alerts(events, rules, baseline),
        analysis / "alerts",
        {"processed_events": len(events), "skipped_invalid_time": skipped},
    )
    return service.run_demo()


def main() -> None:
    result = run_pipeline(Path("/data/events.csv"), Path("analysis"))
    print(f"Demo completada: {result['created_alerts']} alertas nuevas.")


if __name__ == "__main__":
    main()
