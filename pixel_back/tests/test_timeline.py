from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy.dialects import postgresql

from app.moderation.timeline import _continuous_density_buckets, _modification_density_statement


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

    def test_continuous_density_keeps_quiet_intervals_and_selected_bounds(self):
        start = datetime(2026, 8, 20, 12, 18, tzinfo=timezone.utc)
        end = datetime(2026, 8, 21, 0, 18, tzinfo=timezone.utc)
        buckets = _continuous_density_buckets(
            start,
            end,
            interval=timedelta(hours=6),
            hourly_counts={
                datetime(2026, 8, 20, 12, tzinfo=timezone.utc): 3,
                datetime(2026, 8, 20, 18, tzinfo=timezone.utc): 4,
            },
        )

        self.assertEqual(3, len(buckets))
        self.assertEqual(start.isoformat(), buckets[0]['start'])
        self.assertEqual(end.isoformat(), buckets[-1]['end'])
        self.assertEqual([3, 4, 0], [bucket['count'] for bucket in buckets])
