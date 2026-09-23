# Project Planner

A PyQt6 desktop app for planning a project as a set of **activities**. Each
activity has a unique ID, a short title, a rich-text scope of work, effort in
hours, status, owner, and dependencies on other activities.

## Run

```bash
uv run python -m projectplanner            # reopens the last project
uv run python -m projectplanner plan.pplan # or open or create a specific file
```

## Use

- **Activity ▸ New** (⌘N) adds an activity. Edit it in the right-hand panel and
  save it with **Save Activity** (⌘S).
- **Depends on** takes activity IDs such as `3, 7, 12`. Unknown IDs, an
  activity depending on itself, and dependency cycles are rejected.
- **Total effort** is the hours needed to complete that activity alone.
- Right-click a row to delete it, or press Delete. Links from activities that
  depended on the deleted one are removed.
- **File ▸ Export to Excel** (⌘E) writes every activity to an `.xlsx` file.

## Storage

A project is a single SQLite file (`*.pplan`). Changes go to the file as soon
as you save an activity. A new project starts in memory until you use
**File ▸ Save Project As**.

## Development

```bash
uv run pytest
```

The package runs from source (`package = false` in `pyproject.toml`) because uv
on this Mac hides editable-install `.pth` files. At startup
`projectplanner/compat.py` clears the same hidden flag from Qt's plugins.
