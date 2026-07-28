from datetime import datetime

from live_sample import sample_checkpoint


def test_sample_uses_boundary_when_more_than_limit_exists() -> None:
    cursor_time, cursor_id = sample_checkpoint(
        "2026-07-27T10:00:00-05:00",
        "500",
        "2026-07-27T08:00:00-05:00",
        "1",
    )

    assert datetime.fromisoformat(cursor_time) == datetime.fromisoformat(
        "2026-07-27T10:00:00-05:00"
    )
    assert cursor_id == "500"


def test_sample_starts_immediately_before_first_event_for_short_day() -> None:
    cursor_time, cursor_id = sample_checkpoint(
        None,
        None,
        "2026-07-27T08:00:00-05:00",
        "1",
    )

    assert datetime.fromisoformat(cursor_time) < datetime.fromisoformat("2026-07-27T08:00:00-05:00")
    assert cursor_id == "1"
