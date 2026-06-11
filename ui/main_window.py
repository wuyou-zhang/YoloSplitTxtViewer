from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QSize, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.image_index import ImageIndex
from core.split_runner import split_dataset
from core.split_store import SplitStore


class ZoomableGraphicsView(QGraphicsView):
    MIN_SCALE = 0.05
    MAX_SCALE = 20.0
    zoomChanged = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            event.ignore()
            return

        current_scale = self.transform().m11() or 1.0
        factor = 1.15 if delta_y > 0 else 1 / 1.15
        target_scale = current_scale * factor
        if target_scale < self.MIN_SCALE:
            factor = self.MIN_SCALE / current_scale
        elif target_scale > self.MAX_SCALE:
            factor = self.MAX_SCALE / current_scale

        if math.isclose(factor, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            event.accept()
            return

        self.scale(factor, factor)
        self.zoomChanged.emit(self.transform().m11() or 1.0)
        event.accept()

    def reset_zoom(self) -> None:
        self.resetTransform()


class MainWindow(QMainWindow):
    CONFIG_PATH = Path(__file__).parent.parent / "split_config.json"
    DEFAULT_CLASS_COLORS = (
        "#FF3B30",
        "#FF9500",
        "#FFCC00",
        "#34C759",
        "#00C7BE",
        "#007AFF",
        "#5856D6",
        "#FF2D55",
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Soldering Split Viewer")
        self.resize(1400, 900)

        self.split_dir = Path("E:/Desktop/solderingData/split_files")
        self.store = SplitStore(self.split_dir)
        self.indexer = ImageIndex()

        self.current_split = "train"
        self.filtered_paths: list[str] = []
        self.all_items = []
        self.all_items_dirty = True
        self._data_root_reload_pending = False
        self.pixmap_cache: dict[str, QPixmap] = {}
        self.data_root = Path("E:/Desktop/solderingData")
        self.names_path = self.data_root / "solderingHbbclass.txt"

        self._seed_enabled = False
        self._seed_value = 42
        self._train_ratio = 0.9
        self._val_ratio = 0.1
        self._test_ratio = 0.0
        self._class_colors = list(self.DEFAULT_CLASS_COLORS)
        self._zoom_ratio = 1.0
        self._load_config()

        self._build_ui()
        self._connect_config_autosave()
        self.reload_data()

    def _build_ui(self) -> None:
        root = QWidget(self)
        main_layout = QVBoxLayout(root)

        top_bar = QHBoxLayout()
        self.path_label = QLabel("当前路径: -")
        self.meta_label = QLabel("集合: - | 索引: -")
        top_bar.addWidget(self.path_label, 1)
        top_bar.addWidget(self.meta_label, 0)
        main_layout.addLayout(top_bar)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        path_toggle_row = QHBoxLayout()
        self.toggle_paths_btn = QPushButton("显示数据路径")
        self.toggle_paths_btn.clicked.connect(self.toggle_path_panel)
        path_toggle_row.addWidget(self.toggle_paths_btn)
        left_layout.addLayout(path_toggle_row)

        path_group = QGroupBox("数据路径")
        path_group_layout = QVBoxLayout(path_group)
        self.path_group = path_group
        path_group.setVisible(False)

        data_root_row = QHBoxLayout()
        self.data_root_edit = QLineEdit(self._normalize_path(str(self.data_root)))
        self.pick_data_root_btn = QPushButton("数据根目录")
        self.pick_data_root_btn.clicked.connect(self.choose_data_root)
        data_root_row.addWidget(self.data_root_edit, 1)
        data_root_row.addWidget(self.pick_data_root_btn)
        path_group_layout.addLayout(data_root_row)

        self.images_path_label = QLineEdit(self._normalize_path(str(self.data_root / "Images")))
        self.labels_path_label = QLineEdit(self._normalize_path(str(self.data_root / "labels")))
        self.split_files_path_label = QLineEdit(self._normalize_path(str(self.data_root / "split_files")))
        for label in (self.images_path_label, self.labels_path_label, self.split_files_path_label):
            label.setReadOnly(True)
            label.setStyleSheet("QLineEdit { background-color: #f5f5f5; color: #666; }")
            path_group_layout.addWidget(label)
        self.data_root_edit.textChanged.connect(self._update_sub_paths)
        self.data_root_edit.textChanged.connect(lambda _: self._mark_all_items_dirty())
        self.data_root_edit.textChanged.connect(lambda _: self._schedule_data_root_reload())

        names_row = QHBoxLayout()
        self.names_edit = QLineEdit(self._normalize_path(str(self.names_path)))
        self.pick_names_btn = QPushButton("类别文件")
        self.pick_names_btn.clicked.connect(self.choose_names_file)
        names_row.addWidget(self.names_edit, 1)
        names_row.addWidget(self.pick_names_btn)
        path_group_layout.addLayout(names_row)

        left_layout.addWidget(path_group)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按文件名搜索...")
        self.search_edit.textChanged.connect(self.refresh_list)
        left_layout.addWidget(self.search_edit)

        split_switch = QHBoxLayout()
        self.btn_show_train = QPushButton("Train")
        self.btn_show_val = QPushButton("Val")
        self.btn_show_all = QPushButton("All")
        self.btn_show_train.clicked.connect(lambda: self.switch_split("train"))
        self.btn_show_val.clicked.connect(lambda: self.switch_split("val"))
        self.btn_show_all.clicked.connect(lambda: self.switch_split("all"))
        self.btn_show_train.setCheckable(True)
        self.btn_show_val.setCheckable(True)
        self.btn_show_all.setCheckable(True)
        active_btn_style = (
            "QPushButton {"
            "  border: 1px solid #BDBDBD;"
            "  border-radius: 6px;"
            "  padding: 4px 10px;"
            "}"
            "QPushButton:checked {"
            "  background-color: #1976D2;"
            "  color: white;"
            "  border: 1px solid #1565C0;"
            "  border-radius: 6px;"
            "  font-weight: bold;"
            "}"
        )
        self.btn_show_train.setStyleSheet(active_btn_style)
        self.btn_show_val.setStyleSheet(active_btn_style)
        self.btn_show_all.setStyleSheet(active_btn_style)
        split_switch.addWidget(self.btn_show_all)
        split_switch.addWidget(self.btn_show_train)
        split_switch.addWidget(self.btn_show_val)
        left_layout.addLayout(split_switch)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.currentItemChanged.connect(self.on_selection_changed)
        self.list_widget.itemSelectionChanged.connect(self.on_item_selection_changed)
        left_layout.addWidget(self.list_widget, 1)

        move_bar = QHBoxLayout()
        self.move_to_train_btn = QPushButton("移动到 Train")
        self.move_to_val_btn = QPushButton("移动到 Val")
        self.remove_from_split_btn = QPushButton("移除出划分")
        self.move_to_train_btn.clicked.connect(lambda: self.move_selected("train"))
        self.move_to_val_btn.clicked.connect(lambda: self.move_selected("val"))
        self.remove_from_split_btn.clicked.connect(self.remove_selected)
        move_bar.addWidget(self.move_to_train_btn)
        move_bar.addWidget(self.move_to_val_btn)
        move_bar.addWidget(self.remove_from_split_btn)
        left_layout.addLayout(move_bar)

        nav_bar = QHBoxLayout()
        self.prev_btn = QPushButton("上一张")
        self.next_btn = QPushButton("下一张")
        self.prev_btn.clicked.connect(self.select_prev)
        self.next_btn.clicked.connect(self.select_next)
        nav_bar.addWidget(self.prev_btn)
        nav_bar.addWidget(self.next_btn)
        left_layout.addLayout(nav_bar)

        split_group = QGroupBox("数据划分")
        split_group_layout = QVBoxLayout(split_group)
        self.split_group = split_group
        split_group.setVisible(False)  # 默认隐藏

        ratio_row = QHBoxLayout()
        self.train_ratio = QDoubleSpinBox()
        self.val_ratio = QDoubleSpinBox()
        self.test_ratio = QDoubleSpinBox()
        for spin, value in ((self.train_ratio, self._train_ratio), (self.val_ratio, self._val_ratio), (self.test_ratio, self._test_ratio)):
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setValue(value)
        ratio_row.addWidget(QLabel("Train"))
        ratio_row.addWidget(self.train_ratio)
        ratio_row.addWidget(QLabel("Val"))
        ratio_row.addWidget(self.val_ratio)
        ratio_row.addWidget(QLabel("Test"))
        ratio_row.addWidget(self.test_ratio)
        split_group_layout.addLayout(ratio_row)

        seed_row = QHBoxLayout()
        self.seed_checkbox = QCheckBox("固定随机种子")
        self.seed_checkbox.setChecked(self._seed_enabled)
        self.seed_spinbox = QSpinBox()
        self.seed_spinbox.setRange(0, 999999)
        self.seed_spinbox.setValue(self._seed_value)
        self.seed_spinbox.setEnabled(self._seed_enabled)
        self.seed_checkbox.toggled.connect(self.seed_spinbox.setEnabled)
        seed_row.addWidget(self.seed_checkbox)
        seed_row.addWidget(self.seed_spinbox)
        seed_row.addStretch()
        split_group_layout.addLayout(seed_row)

        split_action_row = QHBoxLayout()
        self.run_split_btn = QPushButton("执行划分")
        self.run_split_btn.clicked.connect(self.run_split)
        split_action_row.addWidget(self.run_split_btn)
        split_group_layout.addLayout(split_action_row)

        self.split_log = QTextEdit()
        self.split_log.setReadOnly(True)
        self.split_log.setPlaceholderText("划分日志输出...")
        self.split_log.setMaximumHeight(150)
        split_group_layout.addWidget(self.split_log)

        left_layout.addWidget(split_group)

        split_toggle_row = QHBoxLayout()
        self.toggle_split_panel_btn = QPushButton("显示数据划分")
        self.toggle_split_panel_btn.clicked.connect(self.toggle_split_panel)
        split_toggle_row.addWidget(self.toggle_split_panel_btn)
        left_layout.addLayout(split_toggle_row)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.scene = QGraphicsScene(self)
        self.view = ZoomableGraphicsView(self)
        self.view.setScene(self.scene)
        self.view.zoomChanged.connect(self._on_view_zoom_changed)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        right_layout.addWidget(self.view, 1)

        annotation_group = QGroupBox("标注显示")
        annotation_layout = QVBoxLayout(annotation_group)
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("类别颜色"))
        self.class_color_buttons: list[QPushButton] = []
        for index in range(8):
            button = QPushButton(str(index + 1))
            button.setFixedWidth(32)
            button.clicked.connect(lambda _checked=False, idx=index: self.choose_class_color(idx))
            self.class_color_buttons.append(button)
            color_row.addWidget(button)
        color_row.addStretch()
        annotation_layout.addLayout(color_row)
        right_layout.addWidget(annotation_group)
        self._refresh_class_color_buttons()

        zoom_bar = QHBoxLayout()
        self.fit_btn = QPushButton("适配窗口")
        self.open_split_dir_btn = QPushButton("选择 split_files")
        self.open_split_dir_btn.setEnabled(False)  # 暂时禁用，避免路径混乱
        self.fit_btn.clicked.connect(self.capture_fit_zoom)
        self.open_split_dir_btn.clicked.connect(self.choose_split_dir)
        zoom_bar.addWidget(self.fit_btn)
        zoom_bar.addWidget(self.open_split_dir_btn)
        right_layout.addLayout(zoom_bar)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([420, 980])

        main_layout.addWidget(splitter, 1)

        self.setCentralWidget(root)

        toolbar = QToolBar("Main", self)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        reload_action = QAction("重新加载", self)
        reload_action.setShortcut(QKeySequence.Refresh)
        reload_action.triggered.connect(self.reload_data)
        toolbar.addAction(reload_action)

        self.setStatusBar(QStatusBar(self))

    def _update_sub_paths(self, root_text: str) -> None:
        root = Path(root_text.strip()) if root_text.strip() else Path(".")
        self.images_path_label.setText(self._normalize_path(str(root / "Images")))
        self.labels_path_label.setText(self._normalize_path(str(root / "labels")))
        self.split_files_path_label.setText(self._normalize_path(str(root / "split_files")))

    def _data_root_from_edit(self) -> Path:
        text = self.data_root_edit.text().strip()
        return Path(text) if text else self.data_root

    # ------------------------------------------------------------------
    # config persistence
    # ------------------------------------------------------------------
    def _load_config(self) -> None:
        try:
            if self.CONFIG_PATH.exists():
                data = json.loads(self.CONFIG_PATH.read_text(encoding="utf-8"))
                # 加载时统一路径分隔符
                data_root = self._normalize_path(data.get("data_root", str(self.data_root)))
                names_path = self._normalize_path(data.get("names_path", str(self.names_path)))
                self.data_root = Path(data_root)
                self.names_path = Path(names_path)
                self._train_ratio = float(data.get("train_ratio", 0.9))
                self._val_ratio = float(data.get("val_ratio", 0.1))
                self._test_ratio = float(data.get("test_ratio", 0.0))
                self._seed_enabled = bool(data.get("seed_enabled", False))
                self._seed_value = int(data.get("seed_value", 42))
                colors = data.get("class_colors", list(self.DEFAULT_CLASS_COLORS))
                self._class_colors = self._normalize_class_colors(colors)
                self._zoom_ratio = self._normalize_zoom_ratio(data.get("zoom_ratio", 1.0))
        except Exception:
            pass  # corrupted config → keep defaults

    @staticmethod
    def _normalize_path(text: str) -> str:
        """统一路径分隔符为正斜杠 /"""
        return text.replace("\\", "/") if text else text

    def _save_config(self) -> None:
        data = {
            "data_root": self._normalize_path(self.data_root_edit.text().strip()),
            "names_path": self._normalize_path(self.names_edit.text().strip()),
            "train_ratio": self.train_ratio.value(),
            "val_ratio": self.val_ratio.value(),
            "test_ratio": self.test_ratio.value(),
            "seed_enabled": self.seed_checkbox.isChecked(),
            "seed_value": self.seed_spinbox.value(),
            "class_colors": self._class_colors,
            "zoom_ratio": self._zoom_ratio,
        }
        self.CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _connect_config_autosave(self) -> None:
        self.data_root_edit.textChanged.connect(lambda _: self._save_config())
        self.names_edit.textChanged.connect(lambda _: self._save_config())
        self.train_ratio.valueChanged.connect(lambda _: self._save_config())
        self.val_ratio.valueChanged.connect(lambda _: self._save_config())
        self.test_ratio.valueChanged.connect(lambda _: self._save_config())
        self.seed_checkbox.toggled.connect(lambda _: self._save_config())
        self.seed_spinbox.valueChanged.connect(lambda _: self._save_config())

    def _normalize_class_colors(self, colors: list[str] | tuple[str, ...] | object) -> list[str]:
        valid_colors: list[str] = []
        if isinstance(colors, (list, tuple)):
            for value in colors:
                color = QColor(str(value))
                if color.isValid():
                    valid_colors.append(color.name().upper())
                if len(valid_colors) == 8:
                    break
        while len(valid_colors) < 8:
            valid_colors.append(self.DEFAULT_CLASS_COLORS[len(valid_colors)])
        return valid_colors

    def _normalize_zoom_ratio(self, value: object) -> float:
        try:
            zoom_ratio = float(value)
        except (TypeError, ValueError):
            zoom_ratio = 1.0
        return min(max(zoom_ratio, self.view.MIN_SCALE), self.view.MAX_SCALE) if hasattr(self, "view") else min(max(zoom_ratio, 0.05), 20.0)

    def _refresh_class_color_buttons(self) -> None:
        if not hasattr(self, "class_color_buttons"):
            return
        for index, button in enumerate(self.class_color_buttons):
            color = QColor(self._class_colors[index])
            text_color = "#111111" if color.lightness() > 140 else "#FFFFFF"
            button.setStyleSheet(
                "QPushButton {"
                f"background-color: {color.name()};"
                f"color: {text_color};"
                "border: 1px solid #666666;"
                "border-radius: 4px;"
                "font-weight: bold;"
                "}"
            )
            button.setToolTip(f"类别颜色 {index + 1}: {color.name().upper()}")

    def choose_class_color(self, index: int) -> None:
        current = QColor(self._class_colors[index])
        color = QColorDialog.getColor(current, self, f"选择第 {index + 1} 个类别颜色")
        if not color.isValid():
            return
        self._class_colors[index] = color.name().upper()
        self._refresh_class_color_buttons()
        self._save_config()
        self._reload_current_image()

    def _on_view_zoom_changed(self, zoom_ratio: float) -> None:
        self._zoom_ratio = self._normalize_zoom_ratio(zoom_ratio)
        self._save_config()

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def choose_data_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择数据根目录", self.data_root_edit.text().strip())
        if folder:
            self.data_root_edit.setText(self._normalize_path(folder))

    def choose_names_file(self) -> None:
        initial_dir = self._normalize_path(str(Path(self.names_edit.text()).parent if self.names_edit.text().strip() else self.data_root))
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择类别文件",
            initial_dir,
            "Text Files (*.txt);;All Files (*)",
        )
        if file_path:
            self.names_edit.setText(self._normalize_path(file_path))

    def toggle_split_panel(self) -> None:
        visible = self.split_group.isVisible()
        self.split_group.setVisible(not visible)
        self.toggle_split_panel_btn.setText("显示数据划分" if visible else "隐藏数据划分")

    def toggle_path_panel(self) -> None:
        visible = self.path_group.isVisible()
        self.path_group.setVisible(not visible)
        self.toggle_paths_btn.setText("显示数据路径" if visible else "隐藏数据路径")

    def run_split(self) -> None:
        train = self.train_ratio.value()
        val = self.val_ratio.value()
        test = self.test_ratio.value()
        if train + val + test <= 0:
            QMessageBox.warning(self, "参数错误", "Train/Val/Test 比例和必须大于 0")
            return

        data_root = self.data_root_edit.text().strip()
        names_file = self.names_edit.text().strip()
        if not data_root:
            QMessageBox.warning(self, "参数错误", "请设置数据根目录")
            return

        # 检查是否已存在划分文件
        split_dir = Path(data_root) / "split_files"
        existing_files = []
        for name in ("train.txt", "val.txt", "test.txt", "data.yaml"):
            if (split_dir / name).exists():
                existing_files.append(name)

        if existing_files:
            files_str = "\n".join(f"  • {f}" for f in existing_files)
            reply = QMessageBox.question(
                self,
                "覆盖确认",
                f"以下划分文件已存在：\n{files_str}\n\n是否覆盖？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        seed = self.seed_spinbox.value() if self.seed_checkbox.isChecked() else None
        try:
            result = split_dataset(data_root, names_file, (train, val, test), seed=seed)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "划分失败", str(exc))
            self.split_log.append(f"[ERROR] {exc}")
            return

        seed_str = f"seed={seed}" if seed is not None else "seed=random"
        self.split_log.append(
            f"[OK] Train={result.train_count}, Val={result.val_count}, Test={result.test_count}, "
            f"MissingLabel={result.missing_labels}, {seed_str}"
        )
        self.split_log.append(f"[OK] train.txt: {result.train_path}")
        self.split_log.append(f"[OK] val.txt:   {result.val_path}")
        self.split_log.append(f"[OK] test.txt:  {result.test_path}")
        self.split_log.append(f"[OK] data.yaml: {result.yaml_path}")

        self.split_dir = Path(data_root) / "split_files"
        self.store = SplitStore(self.split_dir)
        self.reload_data()
        self.statusBar().showMessage("划分完成并已刷新列表", 4000)

    def switch_split(self, split_name: str) -> None:
        self.current_split = split_name
        self.btn_show_train.setChecked(split_name == "train")
        self.btn_show_val.setChecked(split_name == "val")
        self.btn_show_all.setChecked(split_name == "all")
        if split_name == "all":
            self.move_to_train_btn.setText("加入 Train")
            self.move_to_val_btn.setText("加入 Val")
        else:
            self.move_to_train_btn.setText("移动到 Train")
            self.move_to_val_btn.setText("移动到 Val")
        self.refresh_list()

    def _current_paths(self) -> list[str]:
        if self.current_split == "train":
            return self.store.data.train
        if self.current_split == "val":
            return self.store.data.val
        return [item.path for item in self.all_items]

    def _refresh_all_items(self) -> None:
        if not self.all_items_dirty:
            return

        split_paths = [*self.store.data.train, *self.store.data.val]
        self.all_items = self.indexer.build_all(self._data_root_from_edit(), split_paths)
        self.all_items_dirty = False

    def _mark_all_items_dirty(self) -> None:
        self.all_items_dirty = True

    def _schedule_data_root_reload(self) -> None:
        if self._data_root_reload_pending:
            return
        self._data_root_reload_pending = True
        QTimer.singleShot(250, self._reload_after_data_root_change)

    def _reload_after_data_root_change(self) -> None:
        self._data_root_reload_pending = False
        self.pixmap_cache.clear()
        self.reload_data()

    def _normalize_loaded_split_paths(self) -> bool:
        images_dir = self.indexer.resolve_images_dir(self._data_root_from_edit())
        if not images_dir.exists():
            return False

        images_root = images_dir.resolve()

        def normalize(path_text: str) -> str:
            path = Path(path_text)
            if not path.exists():
                return path_text
            try:
                rel_path = path.resolve().relative_to(images_root)
            except ValueError:
                return path_text
            return (images_dir / rel_path).as_posix()

        old_train = list(self.store.data.train)
        old_val = list(self.store.data.val)
        self.store.data.train = [normalize(path) for path in self.store.data.train]
        self.store.data.val = [normalize(path) for path in self.store.data.val]
        return self.store.data.train != old_train or self.store.data.val != old_val

    def _save_store_after_change(self, message: str) -> bool:
        try:
            self.store.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "写入失败", str(exc))
            self.reload_data()
            return False

        self.statusBar().showMessage(message, 3000)
        return True

    def _item_status(self, item: QListWidgetItem | None) -> str | None:
        if item is None:
            return None
        return item.data(Qt.UserRole + 1)

    def _selected_items(self) -> list[QListWidgetItem]:
        return self.list_widget.selectedItems()

    def _selected_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for item in self._selected_items():
            path = item.data(Qt.UserRole)
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def _update_move_buttons(self) -> None:
        selected_items = self._selected_items()
        if self.current_split == "all":
            statuses = {self._item_status(item) for item in selected_items}
            can_add = bool(selected_items) and statuses == {"unassigned"}
            self.move_to_train_btn.setEnabled(can_add)
            self.move_to_val_btn.setEnabled(can_add)
            self.remove_from_split_btn.setEnabled(False)
            return

        has_selection = bool(selected_items)
        self.move_to_train_btn.setEnabled(has_selection and self.current_split != "train")
        self.move_to_val_btn.setEnabled(has_selection and self.current_split != "val")
        self.remove_from_split_btn.setEnabled(has_selection)

    def refresh_list(self, preferred_path: str | None = None, preferred_row: int | None = None) -> None:
        current_text = self.search_edit.text().strip().lower()
        previous_row = self.list_widget.currentRow() if preferred_row is None else preferred_row
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()

        try:
            if self.current_split == "all":
                self._refresh_all_items()

            paths = self._current_paths()
            self.filtered_paths = []
            all_status = {item.path: item for item in self.all_items} if self.current_split == "all" else {}

            index = 0
            for p in paths:
                name = Path(p).name.lower()
                if current_text and current_text not in name:
                    continue

                index += 1
                self.filtered_paths.append(p)
                item = QListWidgetItem(f"{index}. {Path(p).name}")
                item.setData(Qt.UserRole, p)
                tooltip = p
                if self.current_split == "all":
                    image_item = all_status[p]
                    item.setData(Qt.UserRole + 1, image_item.status)
                    if image_item.status == "missing_label":
                        item.setBackground(QColor("#F8D7DA"))
                        item.setForeground(QColor("#111111"))
                        tooltip = f"{p}\n缺少对应标签"
                    elif image_item.status == "unassigned":
                        item.setBackground(QColor("#FFF3CD"))
                        item.setForeground(QColor("#111111"))
                        tooltip = f"{p}\n未划分，可加入 Train 或 Val"
                    else:
                        tooltip = f"{p}\n已划分"
                elif not Path(p).exists():
                    item.setForeground(Qt.red)
                    tooltip = f"{p}\n文件不存在"
                item.setToolTip(tooltip)
                self.list_widget.addItem(item)
        finally:
            self.list_widget.setUpdatesEnabled(True)

        if self.list_widget.count() > 0:
            if preferred_path:
                self._select_path(preferred_path)
            elif 0 <= previous_row < self.list_widget.count():
                self.list_widget.setCurrentRow(previous_row)
            else:
                self.list_widget.setCurrentRow(0)
        else:
            self.path_label.setText("当前路径: -")
            self.meta_label.setText(f"集合: {self.current_split} | 索引: 0/0")
            self.show_placeholder("无可显示图片")
            self._update_move_buttons()

    def on_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return

        path = current.data(Qt.UserRole)
        self._update_move_buttons()
        if len(self._selected_items()) > 1:
            self.path_label.setText(f"当前路径: {path}")
            return

        index = self.list_widget.currentRow() + 1
        total = self.list_widget.count()
        self.path_label.setText(f"当前路径: {path}")
        self.meta_label.setText(f"集合: {self.current_split} | 索引: {index}/{total}")
        self.load_image(path)

    def on_item_selection_changed(self) -> None:
        selected_count = len(self._selected_items())
        if selected_count > 1:
            self.meta_label.setText(f"集合: {self.current_split} | 已选择: {selected_count}")
            current = self.list_widget.currentItem()
            if current is not None:
                self.path_label.setText(f"当前路径: {current.data(Qt.UserRole)}")
        self._update_move_buttons()

    def load_image(self, path: str) -> None:
        pixmap = self.pixmap_cache.get(path)
        if pixmap is None:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                if len(self.pixmap_cache) >= 24:
                    self.pixmap_cache.pop(next(iter(self.pixmap_cache)))
                self.pixmap_cache[path] = pixmap
        if pixmap.isNull():
            self.show_placeholder("图片加载失败或格式不支持")
            return

        self.scene.clear()
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self._draw_annotations(path, pixmap)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        QTimer.singleShot(0, self.apply_zoom_ratio)

    def _reload_current_image(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            return
        path = current.data(Qt.UserRole)
        if path:
            self.load_image(path)

    def _draw_annotations(self, image_path: str, pixmap: QPixmap) -> None:
        label_path = self._label_path_for_image(image_path)
        if label_path is None or not label_path.exists():
            return

        image_width = pixmap.width()
        image_height = pixmap.height()
        if image_width <= 0 or image_height <= 0:
            return

        try:
            lines = label_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            try:
                lines = label_path.read_text(encoding="gbk").splitlines()
            except OSError:
                return
        except OSError:
            return

        for line in lines:
            parts = line.strip().split()
            if len(parts) not in (5, 9):
                continue
            try:
                class_id = int(float(parts[0]))
            except ValueError:
                continue

            color = QColor(self._class_colors[class_id % len(self._class_colors)])
            pen = QPen(color)
            pen.setWidth(2)

            if len(parts) == 5:
                rect_item = self._build_hbb_item(parts[1:], image_width, image_height, pen)
                if rect_item is not None:
                    self.scene.addItem(rect_item)
                continue

            polygon_item = self._build_obb_item(parts[1:], image_width, image_height, pen)
            if polygon_item is not None:
                self.scene.addItem(polygon_item)

    def _label_path_for_image(self, image_path: str) -> Path | None:
        image_file = Path(image_path)
        images_dir = self.indexer.resolve_images_dir(self._data_root_from_edit())
        try:
            rel_path = image_file.resolve().relative_to(images_dir.resolve())
        except (OSError, ValueError):
            return None
        return self._data_root_from_edit() / "labels" / rel_path.with_suffix(".txt")

    def _build_hbb_item(
        self,
        coords: list[str],
        image_width: int,
        image_height: int,
        pen: QPen,
    ) -> QGraphicsRectItem | None:
        try:
            center_x, center_y, width, height = (float(value) for value in coords)
        except ValueError:
            return None

        rect_width = width * image_width
        rect_height = height * image_height
        x = (center_x * image_width) - rect_width / 2
        y = (center_y * image_height) - rect_height / 2
        item = QGraphicsRectItem(x, y, rect_width, rect_height)
        item.setPen(pen)
        return item

    def _build_obb_item(
        self,
        coords: list[str],
        image_width: int,
        image_height: int,
        pen: QPen,
    ) -> QGraphicsPolygonItem | None:
        if len(coords) != 8:
            return None
        try:
            values = [float(value) for value in coords]
        except ValueError:
            return None

        points = [
            QPointF(values[index] * image_width, values[index + 1] * image_height)
            for index in range(0, 8, 2)
        ]
        item = QGraphicsPolygonItem(QPolygonF(points))
        item.setPen(pen)
        return item

    def show_placeholder(self, text: str) -> None:
        self.scene.clear()
        placeholder = self.scene.addText(text)
        placeholder.setDefaultTextColor(Qt.gray)
        self.scene.setSceneRect(placeholder.boundingRect())
        self.view.reset_zoom()

    def fit_image(self) -> None:
        self.view.reset_zoom()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def reset_zoom(self) -> None:
        self.view.reset_zoom()

    def apply_zoom_ratio(self) -> None:
        if self.pixmap_item.pixmap().isNull():
            return
        self.view.reset_zoom()
        self.view.scale(self._zoom_ratio, self._zoom_ratio)

    def capture_fit_zoom(self) -> None:
        if self.pixmap_item.pixmap().isNull():
            return
        self.fit_image()
        self._zoom_ratio = self._normalize_zoom_ratio(self.view.transform().m11() or 1.0)
        self._save_config()

    def move_selected(self, target: str) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "提示", "请先选择图片")
            return
        preferred_row = self.list_widget.currentRow()

        if self.current_split == "all":
            selected_items = self._selected_items()
            statuses = {self._item_status(item) for item in selected_items}
            if "missing_label" in statuses:
                QMessageBox.information(self, "不可加入", "选中的图片里包含缺少标签的项，不能加入 Train 或 Val")
                return
            if statuses != {"unassigned"}:
                QMessageBox.information(self, "不可加入", "只能批量加入未划分的黄色图片")
                return

            added_count = 0
            for path in paths:
                if self.store.add(path, target):
                    added_count += 1

            if added_count == 0:
                QMessageBox.information(self, "不可加入", "选中的图片都已经在 Train 或 Val 中")
                self.refresh_list()
                return

            if not self._save_store_after_change(f"已加入 {target}: {added_count} 张图片"):
                return

            self._mark_all_items_dirty()
            preferred_path = None
            if paths:
                preferred_path = paths[-1]
            self.refresh_list(preferred_path=preferred_path, preferred_row=preferred_row)
            return

        moved_count = 0
        for path in paths:
            before_train = path in self.store.data.train
            before_val = path in self.store.data.val
            self.store.move(path, target)
            after_train = path in self.store.data.train
            after_val = path in self.store.data.val
            if (before_train != after_train) or (before_val != after_val):
                moved_count += 1

        if self.store.dirty and not self._save_store_after_change(f"已移动到 {target}: {moved_count} 张图片"):
            return

        preferred_path = paths[-1] if target == self.current_split and paths else None
        self.refresh_list(preferred_path=preferred_path, preferred_row=preferred_row)

    def remove_selected(self) -> None:
        if self.current_split == "all":
            QMessageBox.information(self, "提示", "All 视图中的图片请使用加入 Train/Val，不支持移除出划分")
            return

        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "提示", "请先选择图片")
            return
        preferred_row = self.list_widget.currentRow()

        removed_count = 0
        for path in paths:
            if self.store.remove(path):
                removed_count += 1

        if removed_count == 0:
            QMessageBox.information(self, "提示", "选中的图片没有可移除的划分记录")
            return

        if not self._save_store_after_change(f"已移除 {removed_count} 张图片的划分"):
            return

        self._mark_all_items_dirty()
        self.refresh_list(preferred_row=preferred_row)

    def _select_path(self, path: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == path:
                self.list_widget.setCurrentRow(i)
                return

    def select_prev(self) -> None:
        row = self.list_widget.currentRow()
        if row > 0:
            self.list_widget.setCurrentRow(row - 1)

    def select_next(self) -> None:
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            self.list_widget.setCurrentRow(row + 1)

    def save_data(self) -> None:
        try:
            self.store.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.statusBar().showMessage("保存成功", 3000)

    def reload_data(self) -> None:
        self.data_root = self._data_root_from_edit()
        self.split_dir = self.data_root / "split_files"
        self.store = SplitStore(self.split_dir)
        self._mark_all_items_dirty()
        try:
            self.store.load()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "加载失败", str(exc))
            return

        if self._normalize_loaded_split_paths():
            try:
                self.store.save()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "路径规范化写入失败", str(exc))

        self.switch_split(self.current_split)
        train_count = len(self.store.data.train)
        val_count = len(self.store.data.val)
        self.statusBar().showMessage(f"加载完成: train={train_count}, val={val_count}", 4000)

    def choose_split_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择 split_files 目录", str(self.split_dir))
        if not folder:
            return

        self.split_dir = Path(folder)
        self.store = SplitStore(self.split_dir)
        self.reload_data()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.accept()
