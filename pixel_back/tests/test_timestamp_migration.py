from pathlib import Path
import unittest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / 'alembic'
    / 'versions'
    / '20260831_04_normalize_mixed_legacy_timestamps.py'
)


class TimestampMigrationTests(unittest.TestCase):
    def setUp(self):
        self.source = MIGRATION_PATH.read_text(encoding='utf-8')

    def test_pixel_conversion_uses_the_verified_id_boundary(self):
        self.assertIn('ALTER TABLE pixel_logs', self.source)
        self.assertIn('TYPE TIMESTAMP WITH TIME ZONE', self.source)
        self.assertIn('WHEN id <= {LAST_UTC_PIXEL_LOG_ID}', self.source)
        self.assertIn("created_at AT TIME ZONE 'UTC'", self.source)
        self.assertIn("created_at AT TIME ZONE 'Asia/Shanghai'", self.source)

    def test_snapshot_conversion_uses_pixel_high_water_mark(self):
        self.assertIn('ALTER TABLE canvas_snapshots', self.source)
        self.assertIn('WHEN last_log_id <= {LAST_UTC_PIXEL_LOG_ID}', self.source)
        self.assertNotIn('ALTER TABLE visit_logs', self.source)
