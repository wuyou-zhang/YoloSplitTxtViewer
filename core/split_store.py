from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

from core.image_index import ImageIndex


SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test", "unused")


@dataclass
class SplitData:
    train: list[str] = field(default_factory=list)
    val: list[str] = field(default_factory=list)
    test: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return {name: getattr(self, name) for name in SPLIT_NAMES}


class SplitStore:
    def __init__(self, split_dir: Path) -> None:
        self.split_dir = Path(split_dir)
        self.files = {name: self.split_dir / f"{name}.txt" for name in SPLIT_NAMES}
        self.data = SplitData()
        self.dirty = False

    @staticmethod
    def _normalize_path(raw: str) -> str:
        return Path(raw.strip()).as_posix()

    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _load_file(self, file_path: Path) -> list[str]:
        if not file_path.exists():
            return []

        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        out: list[str] = []
        seen: set[str] = set()
        for line in lines:
            text = line.strip()
            if not text:
                continue
            norm = self._normalize_path(text)
            key = self._path_key(norm)
            if key in seen:
                continue
            seen.add(key)
            out.append(norm)
        return out

    def list_for(self, split_name: str) -> list[str]:
        return getattr(self.data, split_name)

    def load(self) -> SplitData:
        data = SplitData()
        seen: set[str] = set()
        for name in SPLIT_NAMES:
            unique: list[str] = []
            for path in self._load_file(self.files[name]):
                # 同一张图片只保留一个归属（按 train/val/test/unused 顺序优先）
                key = self._path_key(path)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(path)
            setattr(data, name, unique)
        self.data = data
        self.dirty = False
        return self.data

    def add_many(self, paths: list[str], target: str) -> int:
        self._require_name(target)
        existing: set[str] = set()
        for name in SPLIT_NAMES:
            existing.update(self._path_key(p) for p in self.list_for(name))

        target_list = self.list_for(target)
        added = 0
        for path in paths:
            key = self._path_key(path)
            if key in existing:
                continue
            existing.add(key)
            target_list.append(path)
            added += 1
        if added:
            self.dirty = True
        return added

    def move_many(self, paths: list[str], target: str) -> int:
        self._require_name(target)
        unique_paths: list[str] = []
        keys: set[str] = set()
        for path in paths:
            key = self._path_key(path)
            if key in keys:
                continue
            keys.add(key)
            unique_paths.append(path)

        target_list = self.list_for(target)
        target_keys = {self._path_key(p) for p in target_list}
        moved = sum(1 for path in unique_paths if self._path_key(path) not in target_keys)

        changed = False
        for name in SPLIT_NAMES:
            if name == target:
                continue
            current = self.list_for(name)
            kept = [p for p in current if self._path_key(p) not in keys]
            if len(kept) != len(current):
                setattr(self.data, name, kept)
                changed = True

        for path in unique_paths:
            key = self._path_key(path)
            if key in target_keys:
                continue
            target_keys.add(key)
            target_list.append(path)
            changed = True

        if changed:
            self.dirty = True
        return moved

    def remove_many(self, paths: list[str]) -> int:
        keys = {self._path_key(path) for path in paths}
        removed = 0
        for name in SPLIT_NAMES:
            current = self.list_for(name)
            kept = [p for p in current if self._path_key(p) not in keys]
            if len(kept) != len(current):
                removed += len(current) - len(kept)
                setattr(self.data, name, kept)
        if removed:
            self.dirty = True
        return removed

    @staticmethod
    def _require_name(name: str) -> None:
        if name not in SPLIT_NAMES:
            raise ValueError(f"未知的划分名称: {name}")

    @staticmethod
    def _atomic_write(file_path: Path, lines: list[str]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=file_path.parent, newline="\n") as tmp:
            tmp.write("\n".join(lines))
            if lines:
                tmp.write("\n")
            temp_name = tmp.name
        Path(temp_name).replace(file_path)

    def _format_paths(self, paths: list[str]) -> list[str]:
        images_dir = ImageIndex.resolve_images_dir(self.split_dir.parent)
        if not images_dir.exists():
            return [Path(path).as_posix() for path in paths]

        images_root = images_dir.resolve()
        formatted: list[str] = []
        for path in paths:
            try:
                rel_path = Path(path).resolve().relative_to(images_root)
            except (OSError, ValueError):
                formatted.append(Path(path).as_posix())
                continue
            formatted.append((images_dir / rel_path).as_posix())
        return formatted

    def save(self) -> None:
        for name in SPLIT_NAMES:
            self._atomic_write(self.files[name], self._format_paths(self.list_for(name)))
        self.dirty = False
