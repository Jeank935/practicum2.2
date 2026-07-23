import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adfs_schema import SOURCE_COLUMNS  # noqa: E402
from normalize_events import (  # noqa: E402
    NormalizationConfig,
    canonicalize_user,
    normalize_csv,
    normalize_record,
)


def valid_record(event_id: str = "99") -> dict[str, str]:
    record = {column: "" for column in SOURCE_COLUMNS}
    record.update(
        {
            "id": "1",
            "event_name": "Fresh Credential Validation Error",
            "log_source": "ADFS_TEST",
            "event_count": "1",
            "event_time": "2026-03-16 10:00:00 +00:00",
            "created_at": "2026-03-16 10:01:00 +00:00",
            "event_id": event_id,
            "low_level_category": "User Login Failure",
            "source_ip": "10.0.0.1",
            "destination_ip": "10.0.0.2",
            "username": "collector",
            "custom_user_id": r"UTPL\real-user-for-test",
            "custom_ip_address": "203.0.113.10",
            "custom_relying_party": "urn:test",
            "event_type_id": "1203",
        }
    )
    return record


class NormalizeEventsTests(unittest.TestCase):
    def test_user_formats_converge_to_same_identity(self):
        domain_user, domain_format = canonicalize_user(r"UTPL\jcuenca")
        email_user, email_format = canonicalize_user("jcuenca@utpl.edu.ec")

        self.assertEqual(domain_user, "jcuenca")
        self.assertEqual(email_user, "jcuenca")
        self.assertEqual(domain_format, "domain_backslash_user")
        self.assertEqual(email_format, "email_like")

    def test_invalid_time_and_type_mismatch_are_flagged(self):
        record = {
            "id": "1",
            "event_name": "Application Token Success",
            "log_source": "ADFS_TEST",
            "event_count": "1",
            "event_time": "1970-12-31 12:00:00 +00:00",
            "created_at": "2026-03-13 20:00:00 +00:00",
            "updated_at": "",
            "event_id": "99",
            "low_level_category": "User Login Success",
            "source_ip": "10.0.0.1",
            "destination_ip": "10.0.0.1",
            "username": "collector",
            "custom_user_id": r"UTPL\jcuenca",
            "custom_ip_address": "203.0.113.10",
            "custom_relying_party": "urn:test",
            "custom_message": "",
            "event_type_id": "1210",
            "event_time_origen": "",
        }

        normalized = normalize_record(record, b"test-secret", 2020)

        self.assertEqual(normalized["event_class"], "success")
        self.assertEqual(normalized["event_time_utc"], "")
        self.assertIn("INVALID_EVENT_TIME", normalized["quality_flags"])
        self.assertIn("EVENT_TYPE_MISMATCH", normalized["quality_flags"])
        self.assertNotIn("jcuenca", normalized["user_key"])

    def test_invalid_ip_and_missing_fields_are_flagged_without_exposure(self):
        record = {
            "id": "2",
            "event_name": "Fresh Credential Validation Error",
            "log_source": "ADFS_TEST",
            "event_count": "0",
            "event_time": "2026-03-16 10:00:00 +00:00",
            "created_at": "",
            "updated_at": "",
            "event_id": "",
            "low_level_category": "User Login Failure",
            "source_ip": "10.0.0.1",
            "destination_ip": "10.0.0.2",
            "username": "collector",
            "custom_user_id": "",
            "custom_ip_address": "not-an-ip",
            "custom_relying_party": "N/A",
            "custom_message": "",
            "event_type_id": "1203",
            "event_time_origen": "",
        }
        normalized = normalize_record(record, b"test-secret", 2020)
        flags = normalized["quality_flags"]
        self.assertIn("INVALID_CLIENT_IP", flags)
        self.assertIn("MISSING_USER_ID", flags)
        self.assertIn("MISSING_SOURCE_EVENT_ID", flags)
        self.assertIn("INVALID_EVENT_COUNT", flags)
        self.assertNotIn("ADFS_TEST", normalized.values())

    def test_rejections_deduplication_and_sanitized_outputs(self):
        config = NormalizationConfig(
            minimum_year=2020,
            rejection_flags=frozenset({"INVALID_CLIENT_IP"}),
        )
        duplicate = valid_record()
        invalid = valid_record("100")
        invalid["custom_ip_address"] = "real-invalid-ip-value"
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            source = root / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                for record in (valid_record(), duplicate, invalid):
                    writer.writerow([record[column] for column in SOURCE_COLUMNS])
            stats = normalize_csv(
                source,
                root / "normalized.csv",
                root / "rejected.csv",
                root / "stats.json",
                b"external-test-key",
                config,
            )
            self.assertEqual(stats["valid_rows"], 1)
            self.assertEqual(stats["rejected_rows"], 2)
            self.assertEqual(stats["duplicate_rows"], 1)
            rejected = (root / "rejected.csv").read_text(encoding="utf-8")
            self.assertNotIn("real-user-for-test", rejected)
            self.assertNotIn("real-invalid-ip-value", rejected)
            self.assertEqual(json.loads((root / "stats.json").read_text())["valid_rows"], 1)


if __name__ == "__main__":
    unittest.main()
