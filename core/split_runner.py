from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from core.image_index import IMAGE_EXTENSIONS, ImageIndex


@dataclass
class SplitResult:
    train_count: int
    val_count: int
    test_count: int
    missing_labels: int
    train_path: Path
    val_path: Path
    test_path: Path
    yaml_path: Path
    class_count: int
    class_names: list[str]


def split_dataset(
    data_root: str | Path,
    names_path: str | Path,
    split_ratio: tuple[float, float, float] = (0.8, 0.1, 0.1),
    extensions: tuple[str, ...] = IMAGE_EXTENSIONS,
    seed: int | None = None,
) -> SplitResult:
    root_path = Path(data_root).resolve()
    images_dir = ImageIndex.resolve_images_dir(root_path)
    labels_dir = root_path / "labels"
    output_dir = root_path / "split_files"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not images_dir.exists():
        raise FileNotFoundError(f"找不到 Images/images 文件夹: {images_dir}")

    images: list[Path] = []
    for ext in extensions:
        images.extend(list(images_dir.rglob(f"*{ext}")))
        images.extend(list(images_dir.rglob(f"*{ext.upper()}")))
    # 去重：Windows 大小写不敏感，同一文件可能被 *.jpg 和 *.JPG 各匹配一次
    seen: set[str] = set()
    unique_images: list[Path] = []
    for p in images:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique_images.append(p)
    images = unique_images

    if not images:
        raise ValueError("未找到任何图片，请检查路径或后缀名。")

    def format_split_image_path(img_path: Path) -> str:
        rel_path = img_path.relative_to(images_dir)
        return str(root_path / "images" / rel_path)

    valid_images: list[str] = []
    missing_labels = 0
    for img_path in images:
        rel_path = img_path.relative_to(images_dir)
        label_path = labels_dir / rel_path.with_suffix(".txt")
        if label_path.exists():
            valid_images.append(format_split_image_path(img_path))
        else:
            missing_labels += 1

    if not valid_images:
        raise ValueError("所有图片都缺失对应标签，无法划分。")

    if seed is not None:
        random.seed(seed)
    random.shuffle(valid_images)
    total = len(valid_images)

    val_count = int(total * split_ratio[1])
    test_count = int(total * split_ratio[2])
    if val_count == 0 and split_ratio[1] > 0:
        val_count = 1
    if test_count == 0 and split_ratio[2] > 0:
        test_count = 1

    train_count = total - val_count - test_count
    if train_count <= 0:
        train_count = total
        val_count = 0
        test_count = 0

    train_imgs = valid_images[:train_count]
    val_imgs = valid_images[train_count : train_count + val_count]
    test_imgs = valid_images[train_count + val_count :]

    def write_txt(filename: str, img_list: list[str]) -> Path:
        p = output_dir / filename
        p.write_text("\n".join(img_list) + ("\n" if img_list else ""), encoding="utf-8")
        return p

    train_path = write_txt("train.txt", train_imgs)
    val_path = write_txt("val.txt", val_imgs)
    test_path = write_txt("test.txt", test_imgs)

    names_file = Path(names_path)
    class_names: list[str] = []
    if names_file.exists():
        class_names = [line.strip() for line in names_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not class_names:
        class_names = ["object"]
    nc = len(class_names)

    test_line = f"test: {test_path.as_posix()}" if len(test_imgs) > 0 else "# test: (无测试集)"
    yaml_content = f"""# YOLO data config
path: {root_path.as_posix()} # dataset root dir
train: {train_path.as_posix()}
val: {val_path.as_posix()}
{test_line}

# Classes
nc: {nc}
names: {class_names}
"""
    yaml_file = root_path / "data.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    return SplitResult(
        train_count=len(train_imgs),
        val_count=len(val_imgs),
        test_count=len(test_imgs),
        missing_labels=missing_labels,
        train_path=train_path,
        val_path=val_path,
        test_path=test_path,
        yaml_path=yaml_file,
        class_count=nc,
        class_names=class_names,
    )
