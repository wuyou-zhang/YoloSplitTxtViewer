from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SplitItem:
    path: str
    exists: bool


class ImageIndex:
    """Validates image paths and returns normalized split items."""

    def build(self, paths: Iterable[str]) -> list[SplitItem]:
        items: list[SplitItem] = []
        for p in paths:
            norm = str(Path(p))
            items.append(SplitItem(path=norm, exists=Path(norm).exists()))
        return items
