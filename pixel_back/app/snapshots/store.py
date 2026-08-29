from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from PIL import Image


class SnapshotError(RuntimeError):
    pass


class SnapshotStore:
    """Filesystem adapter.  Database rows contain only a safe filename."""

    def __init__(self, directory: Path, width: int, height: int) -> None:
        self.directory = directory.resolve()
        self.width = width
        self.height = height

    def ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.is_dir():
            raise SnapshotError(f'snapshot path is not a directory: {self.directory}')
        probe = self.directory / '.write-probe'
        try:
            probe.write_bytes(b'')
        finally:
            probe.unlink(missing_ok=True)

    def path_for(self, filename: str) -> Path:
        if Path(filename).name != filename or not filename.endswith(('.png', '.json')):
            raise SnapshotError('unsafe snapshot filename')
        path = (self.directory / filename).resolve()
        if path.parent != self.directory:
            raise SnapshotError('snapshot path escaped storage directory')
        return path

    def load_array(self, filename: str, expected_sha256: str | None = None) -> NDArray[np.uint8]:
        path = self.path_for(filename)
        if not path.is_file():
            raise SnapshotError(f'snapshot file does not exist: {filename}')
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 and digest != expected_sha256:
            raise SnapshotError(f'snapshot checksum mismatch: {filename}')
        try:
            if path.suffix == '.json':
                colors = json.loads(payload.decode('utf-8'))
                if not isinstance(colors, list) or len(colors) != self.width * self.height:
                    raise ValueError('invalid legacy snapshot shape')
                array = np.full((self.height, self.width, 3), 255, dtype=np.uint8)
                for index, color in enumerate(colors):
                    if not isinstance(color, str) or len(color) != 7 or not color.startswith('#'):
                        raise ValueError('invalid legacy snapshot color')
                    array[index // self.width, index % self.width] = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
            else:
                with Image.open(path) as image:
                    rgb = image.convert('RGB')
                    if rgb.size != (self.width, self.height):
                        raise ValueError(f'expected {self.width}x{self.height}, got {rgb.size}')
                    array = np.asarray(rgb, dtype=np.uint8).copy()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise SnapshotError(f'invalid snapshot {filename}: {error}') from error
        if array.shape != (self.height, self.width, 3):
            raise SnapshotError('invalid snapshot dimensions')
        return array

    def checksum(self, filename: str) -> str:
        return hashlib.sha256(self.path_for(filename).read_bytes()).hexdigest()

    def write_array(self, array: NDArray[np.uint8], event_id: int) -> tuple[str, str]:
        if array.shape != (self.height, self.width, 3):
            raise SnapshotError('attempted to write a snapshot with invalid dimensions')
        filename = f'canvas-{event_id}-{uuid4().hex}.png'
        destination = self.path_for(filename)
        file_descriptor, temporary_name = tempfile.mkstemp(prefix='.canvas-', suffix='.png', dir=self.directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, 'wb') as stream:
                Image.fromarray(array).save(stream, format='PNG', optimize=False)
                stream.flush()
                os.fsync(stream.fileno())
            payload = temporary.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            # Verify before publishing an atomically visible file.
            self.load_array_from_path(temporary)
            os.replace(temporary, destination)
            return filename, digest
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def write_preview(self, array: NDArray[np.uint8], preview_id: str) -> str:
        if Path(preview_id).name != preview_id or not preview_id:
            raise SnapshotError('unsafe preview id')
        filename = f'preview-{preview_id}.png'
        destination = self.path_for(filename)
        temporary = destination.with_suffix('.tmp')
        try:
            Image.fromarray(array).save(temporary, format='PNG')
            os.replace(temporary, destination)
            return filename
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def load_array_from_path(self, path: Path) -> NDArray[np.uint8]:
        with Image.open(path) as image:
            rgb = image.convert('RGB')
            if rgb.size != (self.width, self.height):
                raise SnapshotError('temporary snapshot has invalid dimensions')
            return np.asarray(rgb, dtype=np.uint8)
