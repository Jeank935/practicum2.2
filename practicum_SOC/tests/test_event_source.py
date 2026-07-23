import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from event_source import (  # noqa: E402
    CsvEventSource,
    IncrementalCursor,
    PostgresEventSource,
    quote_identifier,
)
from normalize_events import SOURCE_COLUMNS  # noqa: E402


def raw_row(event_id, timestamp):
    values = {column: "" for column in SOURCE_COLUMNS}
    values.update(
        {
            "id": event_id,
            "event_name": "Fresh Credential Validation Error",
            "log_source": "ADFS_TEST",
            "event_count": "1",
            "event_time": timestamp,
            "created_at": timestamp,
            "event_id": event_id,
            "low_level_category": "User Login Failure",
            "source_ip": "10.0.0.1",
            "destination_ip": "10.0.0.2",
            "username": "collector",
            "custom_user_id": "UTPL\\synthetic",
            "custom_ip_address": "203.0.113.10",
            "custom_relying_party": "urn:synthetic",
            "event_type_id": "1203",
        }
    )
    return [values[column] for column in SOURCE_COLUMNS]


class EventSourceTests(unittest.TestCase):
    def test_checkpoint_uses_timestamp_and_id_without_losing_ties(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            source_path = Path(temp_directory) / "source.csv"
            with source_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(raw_row("11", "2026-03-16 10:00:00 +00:00"))
                writer.writerow(raw_row("10", "2026-03-16 10:00:00 +00:00"))
                writer.writerow(raw_row("12", "2026-03-16 10:01:00 +00:00"))
            source = CsvEventSource(source_path)
            first_batch = source.fetch_after(None, 2)
            self.assertEqual([item.cursor.event_id for item in first_batch], ["10", "11"])
            second_batch = source.fetch_after(first_batch[-1].cursor, 2)
            self.assertEqual([item.cursor.event_id for item in second_batch], ["12"])

    def test_sql_identifiers_are_restricted(self):
        self.assertEqual(quote_identifier("security.adfs_view"), '"security"."adfs_view"')
        with self.assertRaises(ValueError):
            quote_identifier("security.adfs_view; DROP TABLE x")

    def test_postgres_uses_read_only_checkpoint_query_with_mock(self):
        row_values = dict(
            zip(SOURCE_COLUMNS, raw_row("12", "2026-03-16 10:01:00 +00:00"), strict=True)
        )
        result = Mock()
        result.fetchall.return_value = [row_values]
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.side_effect = [Mock(), Mock(), result]
        source = PostgresEventSource(
            dsn="postgresql://synthetic",
            view_name="security.adfs_events",
            retry_attempts=1,
        )
        checkpoint = IncrementalCursor("2026-03-16T10:00:00+00:00", "11")
        with patch.object(source, "_connect", return_value=connection):
            records = source.fetch_after(checkpoint, 50)
        self.assertEqual(records[0].cursor.event_id, "12")
        self.assertIn("READ ONLY", connection.execute.call_args_list[0].args[0])
        query_call = connection.execute.call_args_list[2]
        self.assertIn("WHERE", query_call.args[0])
        self.assertEqual(query_call.args[1][-1], 50)


if __name__ == "__main__":
    unittest.main()
