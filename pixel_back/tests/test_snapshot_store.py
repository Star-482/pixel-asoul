import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.snapshots.store import SnapshotError, SnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def test_round_trip_png_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory), 2, 1)
            store.ensure_directory()
            source = np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
            name, digest = store.write_array(source, 4)
            loaded = store.load_array(name, digest)
            self.assertTrue((loaded == source).all())

    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory), 1, 1)
            with self.assertRaises(SnapshotError):
                store.path_for('../escape.png')
