import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.admin.auth import AdminAuth
from app.admin.previews import AdminPreviewCache
from app.snapshots.store import SnapshotStore


class AdminAuthTests(unittest.TestCase):
    def test_token_verification_and_signed_session(self):
        token = 'a-strong-admin-token'
        auth = AdminAuth(
            hashlib.sha256(token.encode('utf-8')).hexdigest(),
            'session-secret',
            30,
            secure=True,
        )

        self.assertTrue(auth.verify_token(token))
        self.assertFalse(auth.verify_token('wrong-token'))
        cookie, csrf = auth.issue('admin-1')
        payload = auth.decode(cookie)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual('admin-1', payload['sub'])
        self.assertEqual(csrf, payload['csrf'])
        self.assertIsNone(auth.decode(f'{cookie}tampered'))


class AdminPreviewCacheTests(unittest.TestCase):
    def test_expired_preview_is_no_longer_served_and_file_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SnapshotStore(Path(temporary), 1, 1)
            store.ensure_directory()
            filename = 'preview-test-preview.png'
            difference_filename = 'preview-test-preview-diff.png'
            store.path_for(filename).write_bytes(b'preview')
            store.path_for(difference_filename).write_bytes(b'difference')
            cache = AdminPreviewCache(store, ttl_seconds=10)

            with patch('app.admin.previews.monotonic', return_value=100):
                cache.add(
                    preview_id='test-preview',
                    filename=filename,
                    difference_filename=difference_filename,
                    target_event_id=10,
                    head_event_id=20,
                    difference_pixels=3,
                )
                self.assertIsNotNone(cache.get('test-preview'))

            with patch('app.admin.previews.monotonic', return_value=111):
                self.assertIsNone(cache.get('test-preview'))
            self.assertFalse(store.path_for(filename).exists())
            self.assertFalse(store.path_for(difference_filename).exists())
