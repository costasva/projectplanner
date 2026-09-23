"""Entry point: `uv run python -m projectplanner [project-file]`."""
from __future__ import annotations

import sys

from .compat import unhide_qt_plugins


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    unhide_qt_plugins()  # must run before QApplication loads the platform plugin

    from PyQt6.QtWidgets import QApplication

    from .main_window import APP_NAME, MainWindow

    app = QApplication(argv)
    app.setOrganizationName("ProjectPlanner")
    app.setApplicationName(APP_NAME)
    window = MainWindow(argv[1] if len(argv) > 1 else None)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
