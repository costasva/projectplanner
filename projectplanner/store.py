"""Project data: activities and their dependencies, kept in one SQLite file.

The store has no Qt dependency so it can be tested and scripted on its own.
Every change is committed immediately.  An unsaved ("untitled") project lives
in an in-memory database until `save_as` copies it to disk.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Stamped into the SQLite header so we can tell our files from other databases.
APPLICATION_ID = 0x50504C4E  # "PPLN"
SCHEMA_VERSION = 6
FILE_SUFFIX = ".pplan"
HOURS_PER_WEEK = 40

STATUSES = ("Not started", "In progress", "Done", "On hold")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS activities (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL DEFAULT '',
    description_html TEXT    NOT NULL DEFAULT '',
    description_text TEXT    NOT NULL DEFAULT '',
    risks_html       TEXT    NOT NULL DEFAULT '',
    risks_text       TEXT    NOT NULL DEFAULT '',
    duration_weeks   REAL    NOT NULL DEFAULT 0,
    min_duration_ratio REAL  NOT NULL DEFAULT 0.5,
    max_duration_ratio REAL  NOT NULL DEFAULT 2.0,
    status           TEXT    NOT NULL DEFAULT 'Not started',
    owner            TEXT    NOT NULL DEFAULT '',
    group_name       TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS dependencies (
    activity_id   INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, depends_on_id),
    CHECK (activity_id <> depends_on_id)
);
CREATE INDEX IF NOT EXISTS idx_dependencies_depends_on ON dependencies(depends_on_id);
"""


class NotAProjectFileError(Exception):
    """The file exists but is not a Project Planner database."""


class DependencyError(ValueError):
    """A dependency list refers to unknown activities or would form a cycle."""


@dataclass
class Activity:
    id: int | None = None
    title: str = ""
    description_html: str = ""
    description_text: str = ""
    risks_html: str = ""
    risks_text: str = ""
    duration_weeks: float = 0.0
    min_duration_ratio: float = 0.5
    max_duration_ratio: float = 2.0
    status: str = STATUSES[0]
    owner: str = ""
    group_name: str = ""
    depends_on: list[int] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def parse_dependency_ids(text: str) -> list[int]:
    """Parse "3, 7 #12" into [3, 7, 12]; raise ValueError on anything else."""
    ids: list[int] = []
    for token in re.split(r"[,;\s]+", text.strip()):
        if not token:
            continue
        digits = token.lstrip("#")
        if not digits.isdigit():
            raise ValueError(f"'{token}' is not an activity ID")
        value = int(digits)
        if value not in ids:
            ids.append(value)
    return ids


def format_dependency_ids(ids: list[int]) -> str:
    return ", ".join(str(i) for i in sorted(ids))


def transitive_dependencies(activity_id: int, graph: dict[int, list[int]]) -> set[int]:
    """All activities `activity_id` depends on, directly or indirectly."""
    seen: set[int] = set()
    stack = list(graph.get(activity_id, ()))
    while stack:
        dep = stack.pop()
        if dep in seen or dep == activity_id:
            continue
        seen.add(dep)
        stack.extend(graph.get(dep, ()))
    return seen


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ProjectStore:
    def __init__(self, path: str | Path | None = None):
        self.path: Path | None = Path(path) if path else None
        if self.path and self.path.exists():
            self._check_is_project_file(self.path)
        self.conn = self._connect(self.path)
        self._init_schema()

    # ----------------------------------------------------------- lifecycle

    @staticmethod
    def _connect(path: Path | None) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path) if path else ":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _check_is_project_file(path: Path) -> None:
        if path.stat().st_size == 0:
            return
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                tables = conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise NotAProjectFileError(f"{path.name} is not a project file ({exc})") from exc
        if app_id != APPLICATION_ID and tables:
            raise NotAProjectFileError(f"{path.name} is a database from another application")

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA)
            columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(activities)")}
            if "group_name" not in columns:
                self.conn.execute(
                    "ALTER TABLE activities ADD COLUMN group_name TEXT NOT NULL DEFAULT ''"
                )
            if "duration_weeks" not in columns:
                self.conn.execute(
                    "ALTER TABLE activities ADD COLUMN duration_weeks REAL NOT NULL DEFAULT 0"
                )
                if "effort_hours" in columns:
                    self.conn.execute(
                        "UPDATE activities SET duration_weeks = effort_hours / ?",
                        (HOURS_PER_WEEK,),
                    )
            if "effort_hours" in columns:
                self.conn.execute("ALTER TABLE activities DROP COLUMN effort_hours")
            if "risks_html" not in columns:
                self.conn.execute("ALTER TABLE activities ADD COLUMN risks_html TEXT NOT NULL DEFAULT ''")
            if "risks_text" not in columns:
                self.conn.execute("ALTER TABLE activities ADD COLUMN risks_text TEXT NOT NULL DEFAULT ''")
            if "min_duration_ratio" not in columns:
                self.conn.execute(
                    "ALTER TABLE activities ADD COLUMN min_duration_ratio REAL NOT NULL DEFAULT 0.5"
                )
            if "max_duration_ratio" not in columns:
                self.conn.execute(
                    "ALTER TABLE activities ADD COLUMN max_duration_ratio REAL NOT NULL DEFAULT 2.0"
                )
            self.conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schedule_available_people', '2')"
            )

    @property
    def is_untitled(self) -> bool:
        return self.path is None

    def save_as(self, path: str | Path) -> None:
        """Copy the whole project to `path` and continue working on that file."""
        path = Path(path)
        if self.path and path.resolve() == self.path.resolve():
            return
        for stale in (path, path.with_name(path.name + "-journal")):
            stale.unlink(missing_ok=True)
        dest = self._connect(path)
        self.conn.backup(dest)
        self.conn.close()
        self.conn = dest
        self.path = path

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- queries

    def _row_to_activity(self, row: sqlite3.Row, deps: list[int]) -> Activity:
        return Activity(
            id=row["id"],
            title=row["title"],
            description_html=row["description_html"],
            description_text=row["description_text"],
            risks_html=row["risks_html"],
            risks_text=row["risks_text"],
            duration_weeks=row["duration_weeks"],
            min_duration_ratio=row["min_duration_ratio"],
            max_duration_ratio=row["max_duration_ratio"],
            status=row["status"],
            owner=row["owner"],
            group_name=row["group_name"],
            depends_on=deps,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def dependency_graph(self) -> dict[int, list[int]]:
        graph: dict[int, list[int]] = {
            r[0]: [] for r in self.conn.execute("SELECT id FROM activities")
        }
        for aid, dep in self.conn.execute(
            "SELECT activity_id, depends_on_id FROM dependencies ORDER BY depends_on_id"
        ):
            graph[aid].append(dep)
        return graph

    def list_activities(self) -> list[Activity]:
        graph = self.dependency_graph()
        rows = self.conn.execute("SELECT * FROM activities ORDER BY id")
        return [self._row_to_activity(r, graph[r["id"]]) for r in rows]

    def get(self, activity_id: int) -> Activity | None:
        row = self.conn.execute(
            "SELECT * FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            return None
        deps = [
            r[0]
            for r in self.conn.execute(
                "SELECT depends_on_id FROM dependencies WHERE activity_id = ? "
                "ORDER BY depends_on_id",
                (activity_id,),
            )
        ]
        return self._row_to_activity(row, deps)

    def dependents_of(self, activity_id: int) -> list[int]:
        """Activities that list `activity_id` as a dependency."""
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT activity_id FROM dependencies WHERE depends_on_id = ? "
                "ORDER BY activity_id",
                (activity_id,),
            )
        ]

    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM activities").fetchone()[0]

    def project_notes(self) -> tuple[str, str]:
        rows = dict(
            self.conn.execute(
                "SELECT key, value FROM meta WHERE key IN ('project_notes_html', 'project_notes_text')"
            )
        )
        return rows.get("project_notes_html", ""), rows.get("project_notes_text", "")

    def set_project_notes(self, html: str, text: str) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [("project_notes_html", html), ("project_notes_text", text)],
            )

    def available_people(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schedule_available_people'"
        ).fetchone()
        return int(row[0]) if row is not None else 2

    def set_available_people(self, people: int) -> None:
        if people < 1:
            raise ValueError("Available people must be at least 1")
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schedule_available_people', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(people),),
            )

    # ----------------------------------------------------------- mutations

    def validate_dependencies(self, activity_id: int | None, dep_ids: list[int]) -> None:
        graph = self.dependency_graph()
        unknown = [d for d in dep_ids if d not in graph]
        if unknown:
            raise DependencyError(
                "No activity with ID " + ", ".join(str(d) for d in unknown)
            )
        if activity_id is None:
            return
        if activity_id in dep_ids:
            raise DependencyError("An activity cannot depend on itself")
        for dep in dep_ids:
            if activity_id in transitive_dependencies(dep, graph):
                raise DependencyError(
                    f"Depending on {dep} would create a cycle: "
                    f"{dep} already depends on {activity_id}"
                )

    def create(self, activity: Activity | None = None) -> Activity:
        activity = activity or Activity()
        self.validate_dependencies(None, activity.depends_on)
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO activities (title, description_html, description_text, risks_html, risks_text, "
                "duration_weeks, min_duration_ratio, max_duration_ratio, status, owner, group_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    activity.title,
                    activity.description_html,
                    activity.description_text,
                    activity.risks_html,
                    activity.risks_text,
                    activity.duration_weeks,
                    activity.min_duration_ratio,
                    activity.max_duration_ratio,
                    activity.status,
                    activity.owner,
                    activity.group_name,
                    now,
                    now,
                ),
            )
            new_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO dependencies (activity_id, depends_on_id) VALUES (?, ?)",
                [(new_id, d) for d in activity.depends_on],
            )
        return self.get(new_id)

    def update(self, activity: Activity) -> Activity:
        if activity.id is None or self.get(activity.id) is None:
            raise KeyError(f"No activity with ID {activity.id}")
        self.validate_dependencies(activity.id, activity.depends_on)
        with self.conn:
            self.conn.execute(
                "UPDATE activities SET title = ?, description_html = ?, description_text = ?, "
                "risks_html = ?, risks_text = ?, duration_weeks = ?, min_duration_ratio = ?, "
                "max_duration_ratio = ?, status = ?, owner = ?, group_name = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    activity.title,
                    activity.description_html,
                    activity.description_text,
                    activity.risks_html,
                    activity.risks_text,
                    activity.duration_weeks,
                    activity.min_duration_ratio,
                    activity.max_duration_ratio,
                    activity.status,
                    activity.owner,
                    activity.group_name,
                    _now(),
                    activity.id,
                ),
            )
            self.conn.execute(
                "DELETE FROM dependencies WHERE activity_id = ?", (activity.id,)
            )
            self.conn.executemany(
                "INSERT INTO dependencies (activity_id, depends_on_id) VALUES (?, ?)",
                [(activity.id, d) for d in activity.depends_on],
            )
        return self.get(activity.id)

    def delete(self, activity_id: int) -> None:
        """Delete an activity; links from activities that depended on it go too."""
        with self.conn:
            self.conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
