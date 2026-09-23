import sqlite3

import pytest

from projectplanner.store import (
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
    b = store.create(Activity(title="Build", effort_hours=12.5))
    b.description_html = "<p><b>Do</b> it</p>"
    b.description_text = "Do it"
    b.depends_on = [a.id]
    b.status = "In progress"
    store.update(b)
    got = store.get(b.id)
    assert got.depends_on == [a.id]
    assert got.effort_hours == 12.5
    assert got.description_text == "Do it"
    assert store.dependents_of(a.id) == [b.id]


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
    a = store.create(Activity(title="A", effort_hours=2))
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
