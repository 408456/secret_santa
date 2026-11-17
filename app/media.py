from __future__ import annotations

import random
from pathlib import Path

from aiogram.types import FSInputFile

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


class MediaLibrary:
    """Loads drop-in images named event_anything.ext from the assets directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def pick(self, event: str) -> FSInputFile | None:
        if not self.root.exists():
            return None
        matches = [
            path for path in self.root.glob(f"{event}_*")
            if path.is_file() and path.suffix.lower() in SUPPORTED
        ]
        return FSInputFile(random.choice(matches)) if matches else None

