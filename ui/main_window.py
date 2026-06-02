from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsPixmapItem,
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
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._zoom = 1.0

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom *= factor
        self.scale(factor, factor)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom = 1.0


class MainWindow(QMainWindow):
    CONFIG_PATH = Path(__file__).parent.parent / "split_config.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Soldering Split Viewer")
        self.resize(1400, 900)

        self.split_dir = Path("E:/Desktop/solderingData/split_files")
        self.store = SplitStore(self.split_dir)
        self.indexer = ImageIndex()

        self.current_split = "train"
        self.filtered_paths: list[str] = []
        self.data_root = Path("E:/Desktop/solderingData")
        self.names_path = self.data_root / "solderingHbbclass.txt"

        self._seed_enabled = False
        self._seed_value = 42
        self._train_ratio = 0.9
        self._val_ratio = 0.1
        self._test_ratio = 0.0
        self._load_config()

        self._build_ui()
        self._connect_config_autosave()
        self.reload_data()

    def _build_ui(self) -> None:
        root = QWidget(self)
        main_layout = QVBoxLayout(root)

        top_bar = QHBoxLayout()
        tip_label = QLabel("💡 请先执行数据划分生成 split_files 文件夹，或点击「选择 split_files」加载已有划分")
        tip_label.setStyleSheet("color: #666; padding: 4px 0;")
        top_bar.addWidget(tip_label)
        main_layout.addLayout(top_bar)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按文件名搜索...")
        self.search_edit.textChanged.connect(self.refresh_list)
        left_layout.addWidget(self.search_edit)

        split_switch = QHBoxLayout()
        self.btn_show_train = QPushButton("Train")
        self.btn_show_val = QPushButton("Val")
        self.btn_show_train.clicked.connect(lambda: self.switch_split("train"))
        self.btn_show_val.clicked.connect(lambda: self.switch_split("val"))
        self.btn_show_train.setCheckable(True)
        self.btn_show_val.setCheckable(True)
        active_btn_style = (
            "QPushButton:checked {"
            "  background-color: #1976D2;"
            "  color: white;"
            "  border: 1px solid #1565C0;"
            "  font-weight: bold;"
            "}"
        )
        self.btn_show_train.setStyleSheet(active_btn_style)
        self.btn_show_val.setStyleSheet(active_btn_style)
        split_switch.addWidget(self.btn_show_train)
        split_switch.addWidget(self.btn_show_val)
        left_layout.addLayout(split_switch)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.currentItemChanged.connect(self.on_selection_changed)
        left_layout.addWidget(self.list_widget, 1)

        move_bar = QHBoxLayout()
        self.move_to_train_btn = QPushButton("移动到 Train")
        self.move_to_val_btn = QPushButton("移动到 Val")
        self.move_to_train_btn.clicked.connect(lambda: self.move_selected("train"))
        self.move_to_val_btn.clicked.connect(lambda: self.move_selected("val"))
        move_bar.addWidget(self.move_to_train_btn)
        move_bar.addWidget(self.move_to_val_btn)
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

        data_root_row = QHBoxLayout()
        self.data_root_edit = QLineEdit(self._normalize_path(str(self.data_root)))
        self.pick_data_root_btn = QPushButton("数据根目录")
        self.pick_data_root_btn.clicked.connect(self.choose_data_root)
        data_root_row.addWidget(self.data_root_edit, 1)
        data_root_row.addWidget(self.pick_data_root_btn)
        split_group_layout.addLayout(data_root_row)

        self.images_path_label = QLineEdit(self._normalize_path(str(self.data_root / "Images")))
        self.labels_path_label = QLineEdit(self._normalize_path(str(self.data_root / "labels")))
        for label in (self.images_path_label, self.labels_path_label):
            label.setReadOnly(True)
            label.setStyleSheet("QLineEdit { background-color: #f5f5f5; color: #666; }")
            split_group_layout.addWidget(label)
        self.data_root_edit.textChanged.connect(self._update_sub_paths)

        names_row = QHBoxLayout()
        self.names_edit = QLineEdit(self._normalize_path(str(self.names_path)))
        self.pick_names_btn = QPushButton("类别文件")
        self.pick_names_btn.clicked.connect(self.choose_names_file)
        names_row.addWidget(self.names_edit, 1)
        names_row.addWidget(self.pick_names_btn)
        split_group_layout.addLayout(names_row)

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
        self.toggle_split_panel_btn = QPushButton("隐藏数据划分")
        self.toggle_split_panel_btn.clicked.connect(self.toggle_split_panel)
        split_toggle_row.addWidget(self.toggle_split_panel_btn)
        left_layout.addLayout(split_toggle_row)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.scene = QGraphicsScene(self)
        self.view = ZoomableGraphicsView(self)
        self.view.setScene(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        right_layout.addWidget(self.view, 1)

        zoom_bar = QHBoxLayout()
        self.fit_btn = QPushButton("适配窗口")
        self.one_to_one_btn = QPushButton("1:1")
        self.open_split_dir_btn = QPushButton("选择 split_files")
        self.fit_btn.clicked.connect(self.fit_image)
        self.one_to_one_btn.clicked.connect(self.reset_zoom)
        self.open_split_dir_btn.clicked.connect(self.choose_split_dir)
        zoom_bar.addWidget(self.fit_btn)
        zoom_bar.addWidget(self.one_to_one_btn)
        zoom_bar.addWidget(self.open_split_dir_btn)
        right_layout.addLayout(zoom_bar)

        # 当前路径和索引信息
        info_bar = QHBoxLayout()
        self.path_label = QLabel("当前路径: -")
        self.meta_label = QLabel("集合: - | 索引: -")
        info_bar.addWidget(self.path_label, 1)
        info_bar.addWidget(self.meta_label, 0)
        right_layout.addLayout(info_bar)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([420, 980])

        main_layout.addWidget(splitter, 1)

        self.setCentralWidget(root)

        toolbar = QToolBar("Main", self)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        save_action = QAction("保存", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_data)
        toolbar.addAction(save_action)

        reload_action = QAction("重新加载", self)
        reload_action.setShortcut(QKeySequence.Refresh)
        reload_action.triggered.connect(self.reload_data)
        toolbar.addAction(reload_action)

        self.setStatusBar(QStatusBar(self))

    def _update_sub_paths(self, root_text: str) -> None:
        root = Path(root_text.strip()) if root_text.strip() else Path(".")
        self.images_path_label.setText(self._normalize_path(str(root / "Images")))
        self.labels_path_label.setText(self._normalize_path(str(root / "labels")))

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
        self.refresh_list()

    def _current_paths(self) -> list[str]:
        return self.store.data.train if self.current_split == "train" else self.store.data.val

    def refresh_list(self) -> None:
        current_text = self.search_edit.text().strip().lower()
        self.list_widget.clear()

        paths = self._current_paths()
        self.filtered_paths = []

        index = 0
        for p in paths:
            name = Path(p).name.lower()
            if current_text and current_text not in name:
                continue

            index += 1
            self.filtered_paths.append(p)
            item = QListWidgetItem(f"{index}. {Path(p).name}")
            item.setData(Qt.UserRole, p)
            if not Path(p).exists():
                item.setForeground(Qt.red)
                item.setToolTip("文件不存在")
            item.setToolTip(p)
            self.list_widget.addItem(item)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else:
            self.path_label.setText("当前路径: -")
            self.meta_label.setText(f"集合: {self.current_split} | 索引: 0/0")
            self.show_placeholder("无可显示图片")

    def on_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return

        path = current.data(Qt.UserRole)
        index = self.list_widget.currentRow() + 1
        total = self.list_widget.count()
        self.path_label.setText(f"当前路径: {path}")
        self.meta_label.setText(f"集合: {self.current_split} | 索引: {index}/{total}")
        self.load_image(path)

    def load_image(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.show_placeholder("图片加载失败或格式不支持")
            return

        self.scene.clear()
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        QTimer.singleShot(0, self.fit_image)

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

    def _selected_path(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def move_selected(self, target: str) -> None:
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "提示", "请先选择一张图片")
            return

        self.store.move(path, target)

        if target != self.current_split:
            self.refresh_list()
        else:
            self.refresh_list()
            self._select_path(path)

        self.statusBar().showMessage(f"已移动到 {target}: {Path(path).name}", 3000)

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
        try:
            self.store.load()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "加载失败", str(exc))
            return

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
        if not self.store.dirty:
            event.accept()
            return

        reply = QMessageBox.question(
            self,
            "未保存更改",
            "当前有未保存修改，是否保存后退出？",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self.save_data()
            if self.store.dirty:
                event.ignore()
            else:
                event.accept()
        elif reply == QMessageBox.No:
            event.accept()
        else:
            event.ignore()
