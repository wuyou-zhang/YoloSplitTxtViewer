from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass
class SplitData:
    train: list[str]
    val: list[str]


class SplitStore:
    def __init__(self, split_dir: Path, train_name: str = "train.txt", val_name: str = "val.txt") -> None:
        self.split_dir = split_dir
        self.train_file = split_dir / train_name
        self.val_file = split_dir / val_name
        self.data = SplitData(train=[], val=[])
        self.dirty = False

    @staticmethod
    def _normalize_path(raw: str) -> str:
        return str(Path(raw.strip()))

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
            if norm in seen:
                continue
            seen.add(norm)
            out.append(norm)
        return out

    def load(self) -> SplitData:
        self.data = SplitData(
            train=self._load_file(self.train_file),
            val=self._load_file(self.val_file),
        )
        self._enforce_cross_unique()
        self.dirty = False
        return self.data

    def _enforce_cross_unique(self) -> None:
        seen: set[str] = set()
        unique_train: list[str] = []
        for p in self.data.train:
            if p not in seen:
                seen.add(p)
                unique_train.append(p)

        unique_val: list[str] = []
        for p in self.data.val:
            if p not in seen:
                seen.add(p)
                unique_val.append(p)

        self.data.train = unique_train
        self.data.val = unique_val

    def move(self, path: str, target: str) -> None:
        src_list = self.data.train if path in self.data.train else self.data.val if path in self.data.val else None
        if src_list is None:
            return

        if target == "train":
            dst_list = self.data.train
        elif target == "val":
            dst_list = self.data.val
        else:
            raise ValueError("target must be 'train' or 'val'")

        if src_list is dst_list:
            return

        src_list[:] = [p for p in src_list if p != path]
        if path not in dst_list:
            dst_list.append(path)

        self._enforce_cross_unique()
        self.dirty = True

    @staticmethod
    def _atomic_write(file_path: Path, lines: list[str]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=file_path.parent, newline="\n") as tmp:
            tmp.write("\n".join(lines))
            if lines:
                tmp.write("\n")
            temp_name = tmp.name
        Path(temp_name).replace(file_path)

    def save(self) -> None:
        self._atomic_write(self.train_file, self.data.train)
        self._atomic_write(self.val_file, self.data.val)
        self.dirty = False
