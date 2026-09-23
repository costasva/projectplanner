from openpyxl import load_workbook

from projectplanner.excel import export_activities
from projectplanner.store import Activity, ProjectStore


def test_export(tmp_path):
    store = ProjectStore()
    a = store.create(Activity(title="Design", effort_hours=8, description_text="Draw it"))
    store.create(Activity(title="Build", effort_hours=20, depends_on=[a.id]))
    path = tmp_path / "out.xlsx"
    assert export_activities(store, path) == 2

    ws = load_workbook(path).active
    rows = list(ws.iter_rows(min_row=1, max_row=3, values_only=True))
    assert rows[0][:6] == ("ID", "Title", "Depends On", "Required By", "Total Effort (h)", "Status")
    assert rows[1][:6] == (1, "Design", None, "2", 8, "Not started")
    assert rows[2][:6] == (2, "Build", "1", None, 20, "Not started")
    assert rows[1][7] == "Draw it"
    assert ws["E5"].value == "=SUM(E2:E3)"
