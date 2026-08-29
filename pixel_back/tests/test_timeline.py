from datetime import datetime, timezone
import unittest

from sqlalchemy.dialects import postgresql

from app.moderation.timeline import _modification_density_statement


class TimelineQueryTests(unittest.TestCase):
    def test_hour_bucket_is_a_stable_grouping_expression(self):
        statement = _modification_density_statement(
            datetime(2026, 8, 29, tzinfo=timezone.utc),
            datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)

        self.assertIn("date_trunc('hour', pixel_logs.created_at)", sql)
        self.assertNotIn('hour', compiled.params)
