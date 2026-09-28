"""Offscreen smoke test of the main window."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectplanner.compat import unhide_qt_plugins  # noqa: E402

unhide_qt_plugins()

from PyQt6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from projectplanner.main_window import MainWindow  # noqa: E402
from projectplanner.store import Activity  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    QCoreApplication.setOrganizationName("ProjectPlannerTests")
    QCoreApplication.setApplicationName("ProjectPlannerTests")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp("settings")))
    return QApplication.instance() or QApplication([])


def test_create_edit_delete(app, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    w = MainWindow(tmp_path / "p.pplan")

    w.new_activity()
    first = w.editor.activity_id
    w.editor.title.setText("Design")
    w.editor.title.textEdited.emit("Design")
    w.editor.duration.setValue(8)
    w.editor.group.setText("Planning")
    w.editor.scope.edit.setHtml("<p><b>Bold</b> scope</p>")
    w.editor.risks.edit.setHtml("<p>Supplier delay</p>")
    assert w.editor.is_dirty()
    assert w.save_current_activity()

    w.new_activity()
    second = w.editor.activity_id
    w.editor.depends.setText(str(first))
    w.editor.depends.textEdited.emit(str(first))
    w.editor.duration.setValue(4)
    assert w.save_current_activity()

    assert w.proxy.rowCount() == 2
    total_col = w.model.COLUMNS.index("Most likely (weeks)")
    row = [a.id for a in w.model.activities].index(second)
    assert w.model.index(row, total_col).data() == "4"  # own duration only
    assert "font-weight" in w.store.get(first).description_html
    assert w.store.get(first).description_text == "Bold scope"
    assert w.store.get(first).risks_text == "Supplier delay"
    assert w.store.get(first).group_name == "Planning"
    totals = {
        w.group_totals.item(row, 0).text(): [
            w.group_totals.item(row, column).text() for column in range(w.group_totals.columnCount())
        ]
        for row in range(w.group_totals.rowCount())
    }
    assert totals["Project total"] == ["Project total", "12.0", "14.0", "2.8", "10.4", "17.6"]
    assert [w.project_duration_total.item(0, column).text() for column in range(4)] == [
        "12.0", "14.0", "10.4", "17.6"
    ]
    assert w.project_duration_total.item(0, 1).font().bold()
    w.tail_probability.setValue(20)
    assert [w.group_totals.horizontalHeaderItem(column).text() for column in (4, 5)] == [
        "20% limit", "80% limit"
    ]
    w.project_notes.edit.setHtml("<p>Confirm project sponsor</p>")
    assert w.store.project_notes()[1] == "Confirm project sponsor"
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Activities", "Duration Totals", "Project Notes"]

    # Selecting a row shows its details.
    w._select_id(first)
    assert w.editor.title.text() == "Design"
    assert str(second) in w.editor.required_by.text()
    assert w.model.index(0, 0).data(Qt.ItemDataRole.BackgroundRole).name() == "#d9ead3"
    second_row = [a.id for a in w.model.activities].index(second)
    assert w.model.index(second_row, 0).data(Qt.ItemDataRole.ForegroundRole) == Qt.GlobalColor.gray

    second_index = w.proxy.index(second_row, 0)
    w.table.setCurrentIndex(second_index)
    assert w.editor.activity_id == second
    first_row = [a.id for a in w.model.activities].index(first)
    assert w.model.index(first_row, 0).data(Qt.ItemDataRole.ForegroundRole) == Qt.GlobalColor.black
    assert w.model.index(first_row, 0).data(Qt.ItemDataRole.BackgroundRole) is not None
    w.editor.select_dependencies_button.click()
    assert w._selecting_dependencies
    first_index = w.proxy.index(0, 0)
    w.table.setCurrentIndex(first_index)
    assert w.editor.activity_id == second
    w.table.clicked.emit(first_index)
    assert w.editor.depends.text() == ""
    w.table.clicked.emit(first_index)
    assert w.editor.depends.text() == str(first)
    assert w.model.index(first_row, 0).data(Qt.ItemDataRole.BackgroundRole) is not None
    w.editor.select_dependencies_button.click()

    w.delete_activity(first)
    assert w.store.get(first) is None
    assert w.store.get(second).depends_on == []
    w.close()


def test_editor_uses_tight_paragraphs_and_plain_table_rows(app, tmp_path):
    w = MainWindow(tmp_path / "p.pplan")

    assert "margin-top: 0" in w.editor.scope.edit.document().defaultStyleSheet()
    assert "margin-bottom: 0" in w.editor.scope.edit.document().defaultStyleSheet()
    assert w.editor.duration.decimals() == 0
    assert w.editor.min_duration_ratio.value() == 0.5
    assert w.editor.max_duration_ratio.value() == 2.0
    assert w.editor.risks.height() < w.editor.scope.height()
    assert not w.table.alternatingRowColors()
    assert "QTableView::item:selected" in w.table.styleSheet()

    w.close()


def test_sort_controls_sort_by_group(app, tmp_path):
    w = MainWindow(tmp_path / "p.pplan")
    first = w.store.create(Activity(title="Planning", group_name="Planning"))
    second = w.store.create(Activity(title="Build", group_name="Delivery"))
    w._refresh(select_id=None)

    w.sort_by.setCurrentIndex(w.model.COLUMNS.index("Group"))
    assert w.proxy.index(0, 0).data() == str(second.id)

    w.sort_direction.click()
    assert w.proxy.index(0, 0).data() == str(first.id)
    w.close()
