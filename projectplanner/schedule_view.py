"""Schedule tab: capacity input, task timing table, Gantt chart, and resource load."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .scheduler import ProjectSchedule


def gantt_order(schedule: ProjectSchedule):
    """Order lanes chronologically, with stable ties for simultaneous starts."""
    return sorted(
        schedule.activities,
        key=lambda item: (item.start_week, item.end_week, item.activity.id),
    )


def map_scroll_position(value: int, source_minimum: int, source_maximum: int,
                        target_minimum: int, target_maximum: int) -> int:
    """Map a scroll position by relative range, preserving both endpoints."""
    source_span = source_maximum - source_minimum
    if source_span <= 0:
        return target_minimum
    ratio = (value - source_minimum) / source_span
    return round(target_minimum + ratio * (target_maximum - target_minimum))


class _ChartView(QGraphicsView):
    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            return
        super().wheelEvent(event)


class ScheduleView(QWidget):
    """Displays a derived schedule and emits project capacity changes."""

    capacityChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._syncing_gantt_scroll = False
        self.capacity = QSpinBox()
        self.capacity.setRange(1, 10_000)
        self.capacity.setValue(2)
        self.capacity.setSuffix(" people")
        self.capacity.valueChanged.connect(self.capacityChanged)
        self.summary = QLabel()

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Available resources:"))
        controls.addWidget(self.capacity)
        controls.addStretch(1)
        controls.addWidget(self.summary)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Group", "Activity", "Duration", "Start", "End"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (0, 1, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self._gantt_scene = QGraphicsScene(self)
        self._gantt = _ChartView(self._gantt_scene)
        self._gantt.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._gantt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._gantt_header_scene = QGraphicsScene(self)
        self._gantt_header = QGraphicsView(self._gantt_header_scene)
        self._gantt_header.setFixedHeight(30)
        self._gantt_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._gantt_header.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gantt_header.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gantt_header.setFrameShape(QFrame.Shape.NoFrame)
        self._gantt_labels = QTableWidget()
        self._gantt_labels.setColumnCount(2)
        self._gantt_labels.setHorizontalHeaderLabels(["Activity", "Group"])
        self._gantt_labels.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._gantt_labels.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._gantt_labels.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._gantt_labels.verticalHeader().hide()
        self._gantt_labels.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._gantt_labels.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._gantt_labels.setColumnWidth(0, 210)
        self._gantt_labels.setFixedWidth(320)
        self._gantt_labels.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gantt_labels.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gantt_header.setFixedHeight(self._gantt_labels.horizontalHeader().sizeHint().height())
        self._gantt_labels.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_scrollbars(self._gantt_labels.verticalScrollBar(), self._gantt.verticalScrollBar(), value)
        )
        self._gantt.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_scrollbars(self._gantt.verticalScrollBar(), self._gantt_labels.verticalScrollBar(), value)
        )
        self._gantt.horizontalScrollBar().valueChanged.connect(
            lambda value: self._sync_scrollbars(self._gantt.horizontalScrollBar(), self._gantt_header.horizontalScrollBar(), value)
        )
        self._load_scene = QGraphicsScene(self)
        self._load = _ChartView(self._load_scene)
        self._load.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        charts = QSplitter(Qt.Orientation.Vertical)
        gantt_page = QWidget()
        gantt_layout = QVBoxLayout(gantt_page)
        gantt_layout.addWidget(QLabel("Gantt chart (drag to pan, Ctrl+mouse wheel to zoom)"))
        gantt_grid = QGridLayout()
        gantt_grid.setContentsMargins(0, 0, 0, 0)
        gantt_grid.setSpacing(0)
        gantt_grid.addWidget(self._gantt_labels, 0, 0, 2, 1)
        gantt_grid.addWidget(self._gantt_header, 0, 1)
        gantt_grid.addWidget(self._gantt, 1, 1)
        gantt_grid.setColumnStretch(1, 1)
        gantt_grid.setRowStretch(1, 1)
        gantt_layout.addLayout(gantt_grid)
        load_page = QWidget()
        load_layout = QVBoxLayout(load_page)
        load_layout.addWidget(QLabel("Resource load by week"))
        load_layout.addWidget(self._load)
        charts.addWidget(gantt_page)
        charts.addWidget(load_page)
        charts.setStretchFactor(0, 3)
        charts.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(charts, 1)

    def set_available_people(self, people: int) -> None:
        self.capacity.blockSignals(True)
        self.capacity.setValue(people)
        self.capacity.blockSignals(False)

    def _sync_scrollbars(self, source, target, value: int) -> None:
        if self._syncing_gantt_scroll:
            return
        mapped = map_scroll_position(
            value, source.minimum(), source.maximum(), target.minimum(), target.maximum(),
        )
        self._syncing_gantt_scroll = True
        target.setValue(mapped)
        self._syncing_gantt_scroll = False

    def set_schedule(self, schedule: ProjectSchedule) -> None:
        self.summary.setText(f"Project finishes at the end of week {schedule.makespan_weeks}.")
        self.table.setRowCount(len(schedule.activities))
        for row, item in enumerate(schedule.activities):
            activity = item.activity
            values = [
                str(activity.id), activity.group_name, activity.title or "(untitled)",
                str(int(activity.duration_weeks)), str(item.start_week), str(item.end_week),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (0, 3, 4, 5):
                    cell.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                self.table.setItem(row, column, cell)
        self._draw_gantt(schedule)
        self._draw_resource_load(schedule)

    def show_error(self, message: str) -> None:
        self.summary.setText(message)
        self.table.setRowCount(0)
        self._show_chart_message(self._gantt_scene, message)
        self._show_chart_message(self._load_scene, message)

    @staticmethod
    def _show_chart_message(scene: QGraphicsScene, message: str) -> None:
        scene.clear()
        scene.addText(message)

    def _draw_gantt(self, schedule: ProjectSchedule) -> None:
        scene = self._gantt_scene
        scene.clear()
        self._gantt_header_scene.clear()
        week_width, row_height = 56, 28
        makespan = max(schedule.makespan_weeks, 1)
        activities = gantt_order(schedule)
        self._gantt.resetTransform()
        self._gantt_header.resetTransform()
        self._gantt_labels.setRowCount(len(activities))
        for row, item in enumerate(activities):
            self._gantt_labels.setRowHeight(row, row_height)
            activity_cell = QTableWidgetItem(f"{item.activity.id}: {item.activity.title or '(untitled)'}")
            group_cell = QTableWidgetItem(item.activity.group_name or "(Ungrouped)")
            self._gantt_labels.setItem(row, 0, activity_cell)
            self._gantt_labels.setItem(row, 1, group_cell)

        pen = QPen(QColor("#d1d5db"))
        for week in range(makespan + 1):
            x = week * week_width
            scene.addLine(x, 0, x, row_height * len(activities), pen)
            label = self._gantt_header_scene.addText(str(week))
            label.setPos(x + 4, 2)

        rows_by_id = {item.activity.id: row for row, item in enumerate(activities)}
        items_by_id = {item.activity.id: item for item in activities}
        connector_pen = QPen(QColor("#a16207"))
        connector_pen.setWidth(2)
        for dependent in activities:
            dependent_y = rows_by_id[dependent.activity.id] * row_height + row_height / 2
            dependent_start_x = dependent.start_week * week_width
            for prerequisite_id in dependent.activity.depends_on:
                prerequisite = items_by_id.get(prerequisite_id)
                if prerequisite is None:
                    continue
                prerequisite_y = rows_by_id[prerequisite_id] * row_height + row_height / 2
                prerequisite_end_x = prerequisite.end_week * week_width
                vertical = scene.addLine(prerequisite_end_x, prerequisite_y, prerequisite_end_x, dependent_y, connector_pen)
                horizontal = scene.addLine(prerequisite_end_x, dependent_y, dependent_start_x, dependent_y, connector_pen)
                vertical.setZValue(-1)
                horizontal.setZValue(-1)

        for row, item in enumerate(activities):
            y = row * row_height
            scene.addLine(0, y, makespan * week_width, y, pen)
            width = max(4, (item.end_week - item.start_week) * week_width)
            bar = scene.addRect(item.start_week * week_width, y + 4, width, row_height - 8,
                                QPen(QColor("#4f7f7f")), QColor("#cfe8e8"))
            bar.setToolTip(f"Weeks {item.start_week} to {item.end_week}")
        scene.addLine(0, row_height * len(activities), makespan * week_width,
                      row_height * len(activities), pen)
        scene.setSceneRect(0, 0, makespan * week_width + 20, row_height * len(activities) + 1)
        self._gantt_header_scene.setSceneRect(0, 0, makespan * week_width + 20, 28)

    def _draw_resource_load(self, schedule: ProjectSchedule) -> None:
        scene = self._load_scene
        scene.clear()
        left, top, week_width, chart_height = 45, 20, 42, 100
        makespan = max(schedule.makespan_weeks, 1)
        capacity = self.capacity.value()
        max_load = max([capacity, *schedule.resource_load, 1])
        baseline = top + chart_height
        pen = QPen(QColor("#6b7280"))
        scene.addLine(left, baseline, left + makespan * week_width, baseline, pen)
        capacity_y = baseline - chart_height * capacity / max_load
        capacity_line = scene.addLine(left, capacity_y, left + makespan * week_width, capacity_y, QPen(QColor("#c0392b")))
        capacity_line.setToolTip(f"Capacity: {capacity}")
        for week in range(makespan):
            load = schedule.resource_load[week] if week < len(schedule.resource_load) else 0
            height = chart_height * load / max_load
            bar = scene.addRect(left + week * week_width + 4, baseline - height, week_width - 8, height,
                                QPen(QColor("#4f7f7f")), QColor("#cfe8e8"))
            bar.setToolTip(f"Week {week}: {load} people")
            label = scene.addText(str(week))
            label.setPos(left + week * week_width + 12, baseline + 2)
        label = scene.addText(f"Capacity {capacity}")
        label.setPos(0, capacity_y - 10)
        scene.setSceneRect(0, 0, left + makespan * week_width + 20, baseline + 28)
        self._load.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
