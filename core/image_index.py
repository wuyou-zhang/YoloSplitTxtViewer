from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")


@dataclass(frozen=True)
class SplitItem:
    path: str
    exists: bool


@dataclass(frozen=True)
class ImageItem:
    path: str
    has_label: bool
    is_split: bool
    status: str


class ImageIndex:
    """Validates image paths and returns normalized split items."""

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(str(path)))

    def build(self, paths: Iterable[str]) -> list[SplitItem]:
        items: list[SplitItem] = []
        for p in paths:
            norm = str(Path(p))
            items.append(SplitItem(path=norm, exists=Path(norm).exists()))
        return items

    @staticmethod
    def resolve_images_dir(data_root: str | Path) -> Path:
        root = Path(data_root)
        if root.exists():
            children = {child.name: child for child in root.iterdir() if child.is_dir()}
            if "Images" in children:
                return children["Images"]
            if "images" in children:
                return children["images"]

        images_dir = root / "Images"
        if images_dir.exists():
            return images_dir
        return root / "images"

    @staticmethod
    def _collect_images(images_dir: Path) -> list[Path]:
        if not images_dir.exists():
            return []

        images: list[Path] = []
        for ext in IMAGE_EXTENSIONS:
            images.extend(images_dir.rglob(f"*{ext}"))
            images.extend(images_dir.rglob(f"*{ext.upper()}"))

        seen: set[str] = set()
        unique: list[Path] = []
        for path in images:
            key = ImageIndex._path_key(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return sorted(unique, key=lambda p: p.as_posix().lower())

    def build_all(self, data_root: str | Path, split_paths: Iterable[str]) -> list[ImageItem]:
        root = Path(data_root)
        images_dir = self.resolve_images_dir(root)
        labels_dir = root / "labels"
        split_set = {self._path_key(path) for path in split_paths}

        items: list[ImageItem] = []
        for image_path in self._collect_images(images_dir):
            rel_path = image_path.relative_to(images_dir)
            label_path = labels_dir / rel_path.with_suffix(".txt")
            path_text = image_path.as_posix()
            path_key = self._path_key(image_path)
            has_label = label_path.exists()
            is_split = path_key in split_set
            if not has_label:
                status = "missing_label"
            elif not is_split:
                status = "unassigned"
            else:
                status = "assigned"

            items.append(
                ImageItem(
                    path=path_text,
                    has_label=has_label,
                    is_split=is_split,
                    status=status,
                )
            )
        return items
