from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from app.snapshots.store import SnapshotStore


@dataclass(frozen=True, slots=True)
class AdminPreview:
    id: str
    filename: str
    target_event_id: int
    head_event_id: int
    difference_pixels: int
    expires_at: float


class AdminPreviewCache:
    """Short-lived, private timeline preview metadata and files."""

    def __init__(self, store: SnapshotStore, ttl_seconds: float = 600) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds
        self._items: dict[str, AdminPreview] = {}

    def add(
        self,
        *,
        preview_id: str,
        filename: str,
        target_event_id: int,
        head_event_id: int,
        difference_pixels: int,
    ) -> AdminPreview:
        self.cleanup()
        item = AdminPreview(
            id=preview_id,
            filename=filename,
            target_event_id=target_event_id,
            head_event_id=head_event_id,
            difference_pixels=difference_pixels,
            expires_at=monotonic() + self._ttl_seconds,
        )
        self._items[preview_id] = item
        return item

    def get(self, preview_id: str) -> AdminPreview | None:
        self.cleanup()
        return self._items.get(preview_id)

    def cleanup(self) -> None:
        now = monotonic()
        for preview_id, item in tuple(self._items.items()):
            if item.expires_at > now:
                continue
            self._items.pop(preview_id, None)
            try:
                self._store.path_for(item.filename).unlink(missing_ok=True)
            except Exception:
                # A stale preview is never allowed to make the administrative
                # API unavailable. The next filesystem cleanup can remove it.
                continue
