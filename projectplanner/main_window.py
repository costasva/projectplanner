"""Main window: activity list on the left, activity details on the right."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    QUrl,
)
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .editor import ActivityEditor
from .excel import export_activities
from .store import (
    FILE_SUFFIX,
    Activity,
    DependencyError,
    ProjectStore,
    format_dependency_ids,
)

APP_NAME = "Project Planner"
FILE_FILTER = f"Project Planner files (*{FILE_SUFFIX});;SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)"

SORT_ROLE = Qt.ItemDataRole.UserRole
ID_ROLE = Qt.ItemDataRole.UserRole + 1


class ActivityTableModel(QAbstractTableModel):
    COLUMNS = ["ID", "Group", "Title", "Depends On", "Duration (weeks)", "Status"]
    NUMERIC = {0, 4}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.activities: list[Activity] = []

    def set_activities(self, activities: list[Activity]) -> None:
        self.beginResetModel()
        self.activities = activities
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.activities)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        a = self.activities[index.row()]
        col = index.column()
        values = [
            a.id,
            a.group_name,
            a.title,
            format_dependency_ids(a.depends_on),
            a.duration_weeks,
            a.status,
        ]
        if role == Qt.ItemDataRole.DisplayRole:
            v = values[col]
            if col == 4:
                return f"{v:,.0f}"
            if col == 2 and not v:
                return "(untitled)"
            return str(v)
        if role == SORT_ROLE:
            v = values[col]
            return v.lower() if isinstance(v, str) else v
        if role == ID_ROLE:
            return a.id
        if role == Qt.ItemDataRole.TextAlignmentRole and col in self.NUMERIC:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and col == 2:
            text = a.description_text.strip()
            return text[:400] + ("…" if len(text) > 400 else "") if text else None
        if role == Qt.ItemDataRole.ForegroundRole and col == 2 and not a.title:
            return Qt.GlobalColor.gray
        return None


class MainWindow(QMainWindow):
    def __init__(self, path: str | Path | None = None):
        super().__init__()
        self.settings = QSettings()
        self.store: ProjectStore | None = None
        self._restoring_selection = False
        self._untitled_changed = False

        self.model = ActivityTableModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter activities…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(
            "QTableView::item { background: white; }"
            "QTableView::item:selected { background: white; color: black; border: none; }"
            "QTableView::item:focus { border: none; }"
        )
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 50), (1, 120), (3, 110), (4, 110), (5, 95)):
            self.table.setColumnWidth(col, width)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)
        for key in (QKeySequence.StandardKey.Delete, QKeySequence(Qt.Key.Key_Backspace)):
            shortcut = QShortcut(key, self.table)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self.delete_current_activity)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 0, 6)
        left_layout.addWidget(self.filter)
        self.sort_by = QComboBox()
        self.sort_by.addItems(ActivityTableModel.COLUMNS)
        self.sort_by.setToolTip("Choose the column used to sort activities")
        self.sort_by.currentIndexChanged.connect(self._sort_table)
        self.sort_direction = QPushButton("Ascending")
        self.sort_direction.setCheckable(True)
        self.sort_direction.setToolTip("Toggle ascending or descending sort order")
        self.sort_direction.clicked.connect(self._toggle_sort_direction)
        sort_layout = QHBoxLayout()
        sort_layout.addWidget(QLabel("Sort by:"))
        sort_layout.addWidget(self.sort_by, 1)
        sort_layout.addWidget(self.sort_direction)
        left_layout.addLayout(sort_layout)
        left_layout.addWidget(self.table)

        self.group_totals = QTableWidget()
        self.group_totals.setColumnCount(2)
        self.group_totals.setHorizontalHeaderLabels(["Group", "Total time (weeks)"])
        self.group_totals.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.group_totals.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.group_totals.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.group_totals.verticalHeader().hide()
        totals_header = self.group_totals.horizontalHeader()
        totals_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        totals_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.group_totals.setFixedHeight(150)
        left_layout.addWidget(self.group_totals)

        self.editor = ActivityEditor()
        self.editor.saveRequested.connect(self.save_current_activity)
        self.editor.revertRequested.connect(self._revert_editor)
        self.editor.dirtyChanged.connect(lambda _d: self._update_title())

        self.splitter = QSplitter()
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.editor)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self.splitter)

        self._build_actions()
        self.resize(1300, 800)
        self.splitter.setSizes([600, 700])
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("window/splitter")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)

        if path is None:
            last = self.settings.value("lastFile", "", type=str)
            path = last if last and Path(last).exists() else None
        if path is None or not self._open_path(Path(path), quiet=True):
            self._set_store(ProjectStore())

    # ------------------------------------------------------------- actions

    def _build_actions(self) -> None:
        def action(text, slot, shortcut=None, tip=None) -> QAction:
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut is not None:
                a.setShortcut(shortcut)
            if tip:
                a.setStatusTip(tip)
            return a

        self.new_project_action = action("&New Project…", self.new_project,
                                         QKeySequence("Ctrl+Shift+N"), "Start a new, empty project")
        self.open_action = action("&Open Project…", self.open_project,
                                  QKeySequence.StandardKey.Open, "Open a project file")
        self.save_as_action = action("Save Project &As…", self.save_project_as,
                                     QKeySequence.StandardKey.SaveAs, "Save the project to a new file")
        self.export_action = action("&Export to Excel…", self.export_excel,
                                    QKeySequence("Ctrl+E"), "Export all activities to an .xlsx workbook")
        quit_action = action("&Quit", self.close, QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)

        self.new_activity_action = action("&New Activity", self.new_activity,
                                          QKeySequence.StandardKey.New, "Add an activity")
        self.save_activity_action = action("&Save Activity", self.save_current_activity,
                                           QKeySequence.StandardKey.Save, "Save changes to the selected activity")
        self.delete_activity_action = action("&Delete Activity…", self.delete_current_activity,
                                             tip="Delete the selected activity")

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.new_project_action, self.open_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        activity_menu = self.menuBar().addMenu("&Activity")
        activity_menu.addActions([self.new_activity_action, self.save_activity_action])
        activity_menu.addSeparator()
        activity_menu.addAction(self.delete_activity_action)

        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.addActions([self.new_activity_action, self.save_activity_action])
        toolbar.addSeparator()
        toolbar.addAction(self.export_action)

        self.summary_label = QLabel()
        self.statusBar().addPermanentWidget(self.summary_label)

    # ------------------------------------------------------------ projects

    def _set_store(self, store: ProjectStore) -> None:
        if self.store is not None:
            self.store.close()
        self.store = store
        self._untitled_changed = False
        if store.path:
            self.settings.setValue("lastFile", str(store.path))
        self.filter.clear()
        self._refresh(select_id=None)
        if self.model.activities:
            self._select_id(self.model.activities[0].id)
        self._update_title()

    def _open_path(self, path: Path, quiet: bool = False) -> bool:
        try:
            store = ProjectStore(path)
        except Exception as exc:  # noqa: BLE001 - report any failure to open
            if not quiet:
                QMessageBox.critical(self, APP_NAME, f"Could not open {path}:\n\n{exc}")
            return False
        self._set_store(store)
        self.statusBar().showMessage(f"Opened {path}", 5000)
        return True

    def _confirm_discard_untitled(self) -> bool:
        """For an unsaved project with content: offer to save it first."""
        if not (self.store and self.store.is_untitled and self._untitled_changed):
            return True
        answer = QMessageBox.question(
            self, APP_NAME,
            "This project has not been saved to a file yet. Save it now?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project_as()
        return answer == QMessageBox.StandardButton.Discard

    def _ready_to_leave_project(self) -> bool:
        return self._resolve_pending_edits() and self._confirm_discard_untitled()

    def new_project(self) -> None:
        if not self._ready_to_leave_project():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "New Project", str(self._default_dir() / f"Untitled{FILE_SUFFIX}"), FILE_FILTER
        )
        if not path:
            return
        path = self._with_suffix(Path(path))
        path.unlink(missing_ok=True)  # the dialog already confirmed overwriting
        self._open_path(path)

    def open_project(self) -> None:
        if not self._ready_to_leave_project():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", str(self._default_dir()), FILE_FILTER)
        if path:
            self._open_path(Path(path))

    def save_project_as(self) -> bool:
        if not self._resolve_pending_edits():
            return False
        suggested = self.store.path or self._default_dir() / f"Untitled{FILE_SUFFIX}"
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", str(suggested), FILE_FILTER)
        if not path:
            return False
        path = self._with_suffix(Path(path))
        try:
            self.store.save_as(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not save to {path}:\n\n{exc}")
            return False
        self._untitled_changed = False
        self.settings.setValue("lastFile", str(path))
        self._update_title()
        self.statusBar().showMessage(f"Saved to {path}", 5000)
        return True

    def export_excel(self) -> None:
        if not self._resolve_pending_edits():
            return
        stem = self.store.path.stem if self.store.path else "Project"
        start = self.settings.value("lastExportDir", str(self._default_dir()), type=str)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", str(Path(start) / f"{stem} activities.xlsx"),
            "Excel workbooks (*.xlsx)",
        )
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() != ".xlsx":
            path = path.with_name(path.name + ".xlsx")
        try:
            count = export_activities(self.store, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not export to {path}:\n\n{exc}")
            return
        self.settings.setValue("lastExportDir", str(path.parent))
        box = QMessageBox(QMessageBox.Icon.Information, APP_NAME,
                          f"Exported {count} activities to\n{path}", parent=self)
        open_button = box.addButton("Open", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _default_dir(self) -> Path:
        if self.store and self.store.path:
            return self.store.path.parent
        return Path.home() / "Documents"

    @staticmethod
    def _with_suffix(path: Path) -> Path:
        return path if path.suffix else path.with_suffix(FILE_SUFFIX)

    def _update_title(self) -> None:
        if self.store is None:
            return
        name = self.store.path.name if self.store.path else "Untitled"
        self.setWindowTitle(f"{name}[*] — {APP_NAME}")
        self.setWindowFilePath(str(self.store.path) if self.store.path else "")
        self.setWindowModified(self.editor.is_dirty() or (self.store.is_untitled and self._untitled_changed))

    # ---------------------------------------------------------- activities

    def _sort_table(self) -> None:
        order = Qt.SortOrder.DescendingOrder if self.sort_direction.isChecked() else Qt.SortOrder.AscendingOrder
        self.table.sortByColumn(self.sort_by.currentIndex(), order)

    def _toggle_sort_direction(self) -> None:
        self.sort_direction.setText("Descending" if self.sort_direction.isChecked() else "Ascending")
        self._sort_table()

    def _refresh(self, select_id: int | None) -> None:
        """Reload the list from the store and select `select_id` (if given)."""
        self._restoring_selection = True
        try:
            self.model.set_activities(self.store.list_activities())
        finally:
            self._restoring_selection = False
        if select_id is not None:
            self._select_id(select_id)
        elif self.editor.activity_id is not None and self.store.get(self.editor.activity_id) is None:
            self.editor.load(None)
        self._update_status()

    def _select_id(self, activity_id: int, show: bool = True) -> None:
        """Select a row (and show it in the editor) without the unsaved-changes prompt."""
        self._restoring_selection = True
        try:
            for row in range(self.proxy.rowCount()):
                index = self.proxy.index(row, 0)
                if index.data(ID_ROLE) == activity_id:
                    self.table.setCurrentIndex(index)
                    self.table.scrollTo(index)
                    break
            else:
                self.table.clearSelection()
        finally:
            self._restoring_selection = False
        if show:
            self._show_activity(activity_id)

    def _show_activity(self, activity_id: int | None) -> None:
        activity = self.store.get(activity_id) if activity_id is not None else None
        self.editor.load(activity)
        if activity is not None:
            self.editor.set_context(
                {a.id: a.title for a in self.model.activities},
                self.store.dependents_of(activity.id),
            )
        self._update_title()

    def _update_status(self) -> None:
        total = sum(a.duration_weeks for a in self.model.activities)
        n = len(self.model.activities)
        self.summary_label.setText(f"{n} activit{'y' if n == 1 else 'ies'} · {total:,.0f} weeks total duration")

        group_totals: dict[str, float] = {}
        for activity in self.model.activities:
            group_totals[activity.group_name] = group_totals.get(activity.group_name, 0) + activity.duration_weeks
        rows = sorted(group_totals.items(), key=lambda item: item[0].casefold())
        self.group_totals.setRowCount(len(rows) + 1)
        for row, (group, duration) in enumerate(rows):
            self.group_totals.setItem(row, 0, QTableWidgetItem(group or "(Ungrouped)"))
            duration_item = QTableWidgetItem(f"{duration:,.0f}")
            duration_item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            self.group_totals.setItem(row, 1, duration_item)
        total_row = len(rows)
        self.group_totals.setItem(total_row, 0, QTableWidgetItem("Project total"))
        total_item = QTableWidgetItem(f"{total:,.0f}")
        total_item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        self.group_totals.setItem(total_row, 1, total_item)

    def _current_table_id(self) -> int | None:
        index = self.table.currentIndex()
        return index.data(ID_ROLE) if index.isValid() else None

    def _on_current_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._restoring_selection:
            return
        target = current.data(ID_ROLE) if current.isValid() else None
        if target == self.editor.activity_id:
            return
        if not self._resolve_pending_edits():
            # Stay on the activity being edited.
            self._restoring_selection = True
            try:
                self.table.setCurrentIndex(previous)
            finally:
                self._restoring_selection = False
            return
        if target is not None:
            self._select_id(target)
        else:
            self._show_activity(None)

    def _resolve_pending_edits(self) -> bool:
        """Ask what to do with unsaved editor changes.  False means cancel."""
        if not self.editor.is_dirty():
            return True
        answer = QMessageBox.question(
            self, APP_NAME,
            f"Save changes to activity {self.editor.activity_id}?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current_activity()
        if answer == QMessageBox.StandardButton.Discard:
            self._revert_editor()
            return True
        return False

    def _revert_editor(self) -> None:
        self._show_activity(self.editor.activity_id)

    def save_current_activity(self) -> bool:
        if self.editor.activity_id is None or not self.editor.is_dirty():
            return True
        try:
            activity = self.editor.to_activity()
            self.store.update(activity)
        except (ValueError, DependencyError) as exc:
            self.editor.show_dependency_error(str(exc))
            QMessageBox.warning(self, APP_NAME, f"Activity {self.editor.activity_id} was not saved:\n\n{exc}")
            return False
        self._mark_project_changed()
        self._refresh(select_id=activity.id)
        self.statusBar().showMessage(f"Saved activity {activity.id}", 3000)
        return True

    def new_activity(self) -> None:
        if not self._resolve_pending_edits():
            return
        self.filter.clear()
        activity = self.store.create(Activity(title="New activity"))
        self._mark_project_changed()
        self._refresh(select_id=activity.id)
        self.editor.focus_title()

    def delete_current_activity(self) -> None:
        activity_id = self._current_table_id()
        if activity_id is not None:
            self.delete_activity(activity_id)

    def delete_activity(self, activity_id: int) -> None:
        activity = self.store.get(activity_id)
        if activity is None:
            return
        message = f"Delete activity {activity_id} “{activity.title or '(untitled)'}”?"
        dependents = self.store.dependents_of(activity_id)
        if dependents:
            message += (
                "\n\nThese activities depend on it; the dependency will be removed from them: "
                + ", ".join(str(d) for d in dependents)
            )
        if self.editor.activity_id == activity_id and self.editor.is_dirty():
            message += "\n\nUnsaved changes to this activity will be lost."
        answer = QMessageBox.question(
            self, APP_NAME, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # Pick a neighbouring row to select afterwards.
        next_id = None
        row = self.table.currentIndex().row()
        for candidate in (row + 1, row - 1):
            index = self.proxy.index(candidate, 0)
            if index.isValid() and index.data(ID_ROLE) != activity_id:
                next_id = index.data(ID_ROLE)
                break

        keep_editor = self.editor.activity_id != activity_id and self.editor.is_dirty()
        self.store.delete(activity_id)
        self._mark_project_changed()
        if keep_editor:
            # Don't clobber unsaved edits of another activity.
            self._refresh(select_id=None)
            self._select_id(self.editor.activity_id, show=False)
            self.editor.set_context(
                {a.id: a.title for a in self.model.activities},
                self.store.dependents_of(self.editor.activity_id),
            )
        else:
            self.editor.load(None)
            self._refresh(select_id=next_id)
        self.statusBar().showMessage(f"Deleted activity {activity_id}", 3000)

    def _mark_project_changed(self) -> None:
        if self.store.is_untitled:
            self._untitled_changed = True
        self._update_title()

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.table.indexAt(pos)
        menu = QMenu(self)
        menu.addAction(self.new_activity_action)
        if index.isValid():
            activity_id = index.data(ID_ROLE)
            if activity_id != self._current_table_id():
                self.table.setCurrentIndex(index)
                if self._current_table_id() != activity_id:
                    return  # the user cancelled leaving an edited activity
            delete = menu.addAction(f"Delete Activity {activity_id}…")
            delete.triggered.connect(lambda: self.delete_activity(activity_id))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # --------------------------------------------------------------- close

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._ready_to_leave_project():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.splitter.saveState())
        if self.store:
            self.store.close()
            self.store = None
        event.accept()
