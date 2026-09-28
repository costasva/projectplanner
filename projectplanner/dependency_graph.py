"""Graphviz-backed, zoomable activity dependency visualization."""
from __future__ import annotations

import subprocess
import textwrap

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .store import Activity


def _escape_dot(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_dot(activities: list[Activity], selected_id: int | None = None) -> str:
    """Build a layered Graphviz graph, with prerequisites flowing left to right."""
    ids = {activity.id for activity in activities}
    selected = next((activity for activity in activities if activity.id == selected_id), None)
    prerequisites = set(selected.depends_on) if selected else set()
    lines = [
        "digraph dependencies {",
        '  graph [rankdir=LR, bgcolor="transparent", nodesep=0.7, ranksep=1.1, splines=ortho, pad=0.25];',
        '  node [shape=box, style="rounded,filled", color="#4b5563", fontname="Arial", fontsize=10, margin="0.16,0.10"];',
        '  edge [color="#6b7280", arrowsize=0.7, penwidth=1.2];',
    ]
    for activity in activities:
        title = activity.title or "(untitled)"
        label = f"{activity.id}: " + "\n".join(textwrap.wrap(title, width=30) or [title])
        fill = "#d9ead3" if activity.id == selected_id else "#fff3cd" if activity.id in prerequisites else "#ffffff"
        lines.append(f'  activity_{activity.id} [label="{_escape_dot(label)}", fillcolor="{fill}"];')
    for activity in activities:
        for prerequisite in activity.depends_on:
            if prerequisite in ids:
                lines.append(f"  activity_{prerequisite} -> activity_{activity.id};")
    lines.append("}")
    return "\n".join(lines)


class _GraphView(QGraphicsView):
    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class DependencyGraph(QWidget):
    """Renders Graphviz SVG output with pan and wheel-to-zoom interaction."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._view = _GraphView(self._scene)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._renderer: QSvgRenderer | None = None
        self._item: QGraphicsSvgItem | None = None

        self.status = QLabel("Mouse wheel: zoom. Drag: pan.")
        fit_button = QPushButton("Fit graph")
        fit_button.clicked.connect(self.fit_graph)
        controls = QHBoxLayout()
        controls.addWidget(self.status)
        controls.addStretch(1)
        controls.addWidget(fit_button)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._view)

    def update_graph(self, activities: list[Activity], selected_id: int | None = None) -> None:
        if not activities:
            self._show_message("No activities to display.")
            return
        try:
            result = subprocess.run(
                ["dot", "-Tsvg"],
                input=build_dot(activities, selected_id),
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
        except FileNotFoundError:
            self._show_message("Graphviz 'dot' was not found on PATH.")
            return
        except subprocess.CalledProcessError as exc:
            self._show_message(f"Graphviz could not render the dependency graph: {exc.stderr.strip()}")
            return
        except subprocess.TimeoutExpired:
            self._show_message("Graphviz timed out while rendering the dependency graph.")
            return
        self._show_svg(result.stdout.encode())
        self.status.setText("Mouse wheel: zoom. Drag: pan.")

    def fit_graph(self) -> None:
        if self._item is not None:
            self._view.fitInView(self._item.boundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _show_svg(self, svg: bytes) -> None:
        self._scene.clear()
        self._renderer = QSvgRenderer(QByteArray(svg))
        if not self._renderer.isValid():
            self._show_message("Graphviz returned an invalid SVG graph.")
            return
        self._item = QGraphicsSvgItem()
        self._item.setSharedRenderer(self._renderer)
        self._scene.addItem(self._item)
        self.fit_graph()

    def _show_message(self, message: str) -> None:
        self._scene.clear()
        self._item = None
        self._renderer = None
        self._scene.addText(message)
        self.status.setText(message)
