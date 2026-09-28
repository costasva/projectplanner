import sqlite3

import pytest

from projectplanner.store import (
    APPLICATION_ID,
    Activity,
    DependencyError,
    NotAProjectFileError,
    ProjectStore,
    parse_dependency_ids,
)


@pytest.fixture
def store():
    s = ProjectStore()
    yield s
    s.close()


def test_ids_are_unique_and_never_reused(store):
    a = store.create(Activity(title="A"))
    b = store.create(Activity(title="B"))
    store.delete(b.id)
    c = store.create(Activity(title="C"))
    assert len({a.id, b.id, c.id}) == 3


def test_update_round_trip(store):
    a = store.create(Activity(title="Design"))
    b = store.create(Activity(title="Build", duration_weeks=12.5))
    b.description_html = "<p><b>Do</b> it</p>"
    b.description_text = "Do it"
    b.risks_html = "<p>Late supplier</p>"
    b.risks_text = "Late supplier"
    b.min_duration_ratio = 0.75
    b.max_duration_ratio = 1.5
    b.depends_on = [a.id]
    b.status = "In progress"
    b.group_name = "Development"
    store.update(b)
    got = store.get(b.id)
    assert got.depends_on == [a.id]
    assert got.duration_weeks == 12.5
    assert got.description_text == "Do it"
    assert got.risks_text == "Late supplier"
    assert got.min_duration_ratio == 0.75
    assert got.max_duration_ratio == 1.5
    assert got.group_name == "Development"
    assert store.dependents_of(a.id) == [b.id]
    store.set_project_notes("<p>Keep scope small</p>", "Keep scope small")
    assert store.project_notes() == ("<p>Keep scope small</p>", "Keep scope small")


def test_rejects_unknown_self_and_cyclic_dependencies(store):
    a = store.create(Activity(title="A"))
    b = store.create(Activity(title="B", depends_on=[a.id]))
    c = store.create(Activity(title="C", depends_on=[b.id]))
    with pytest.raises(DependencyError, match="No activity"):
        store.update(Activity(id=a.id, title="A", depends_on=[999]))
    with pytest.raises(DependencyError, match="itself"):
        store.update(Activity(id=a.id, title="A", depends_on=[a.id]))
    with pytest.raises(DependencyError, match="cycle"):
        store.update(Activity(id=a.id, title="A", depends_on=[c.id]))
    assert store.get(a.id).depends_on == []


def test_delete_removes_links(store):
    a = store.create(Activity(title="A"))
    b = store.create(Activity(title="B", depends_on=[a.id]))
    store.delete(a.id)
    assert store.get(a.id) is None
    assert store.get(b.id).depends_on == []


def test_parse_dependency_ids():
    assert parse_dependency_ids(" 3, 7 #12;3 ") == [3, 7, 12]
    assert parse_dependency_ids("") == []
    with pytest.raises(ValueError):
        parse_dependency_ids("3, x")


def test_save_as_and_reopen(store, tmp_path):
    a = store.create(Activity(title="A", duration_weeks=2))
    path = tmp_path / "plan.pplan"
    store.save_as(path)
    store.create(Activity(title="B", depends_on=[a.id]))  # written to the file now
    store.close()
    reopened = ProjectStore(path)
    assert [x.title for x in reopened.list_activities()] == ["A", "B"]
    assert reopened.create(Activity(title="C")).id == 3
    reopened.close()


def test_refuses_foreign_files(tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("hello, this is not a database at all" * 10)
    with pytest.raises(NotAProjectFileError):
        ProjectStore(text)
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    with pytest.raises(NotAProjectFileError):
        ProjectStore(other)


def test_opening_legacy_project_adds_empty_group_column(tmp_path):
    path = tmp_path / "legacy.pplan"
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        PRAGMA application_id = {APPLICATION_ID};
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '1');
        CREATE TABLE activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '',
            description_html TEXT NOT NULL DEFAULT '',
            description_text TEXT NOT NULL DEFAULT '',
            effort_hours REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Not started',
            owner TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO activities (title, effort_hours, created_at, updated_at)
        VALUES ('Existing activity', 80, '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        """
    )
    conn.close()

    store = ProjectStore(path)
    assert store.get(1).group_name == ""
    assert store.get(1).duration_weeks == 2
    assert store.get(1).risks_html == ""
    assert store.get(1).risks_text == ""
    assert store.project_notes() == ("", "")
    assert store.get(1).min_duration_ratio == 0.5
    assert store.get(1).max_duration_ratio == 2.0
    assert store.conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "5"
    store.close()

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    assert "group_name" in columns
    assert "duration_weeks" in columns
    assert "effort_hours" not in columns
    assert "risks_html" in columns
    assert "risks_text" in columns
    assert "min_duration_ratio" in columns
    assert "max_duration_ratio" in columns
    assert conn.execute("SELECT group_name FROM activities WHERE id = 1").fetchone()[0] == ""
    assert conn.execute("SELECT duration_weeks FROM activities WHERE id = 1").fetchone()[0] == 2
    conn.close()
