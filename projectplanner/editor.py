"""Detail panel: edits one activity, including its rich-text scope."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QFont,
    QKeySequence,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QTextListFormat,
)
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .store import STATUSES, Activity, format_dependency_ids, parse_dependency_ids

HEADINGS = ["Normal", "Heading 1", "Heading 2", "Heading 3"]


class RichTextEditor(QWidget):
    """A QTextEdit with a small formatting toolbar."""

    textChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        self.edit.document().setDefaultStyleSheet(
            "p { margin-top: 0; margin-bottom: 0; }"
        )
        self.edit.setPlaceholderText("Describe the scope of work for this activity…")
        self.edit.textChanged.connect(self.textChanged)

        bar = QToolBar()

        self.heading = QComboBox()
        self.heading.addItems(HEADINGS)
        self.heading.setToolTip("Paragraph style")
        self.heading.activated.connect(self._set_heading)
        bar.addWidget(self.heading)
        bar.addSeparator()

        self.bold = self._toggle(bar, "B", "Bold", QKeySequence.StandardKey.Bold,
                                 lambda on: self._merge(weight=QFont.Weight.Bold if on else QFont.Weight.Normal))
        self.italic = self._toggle(bar, "I", "Italic", QKeySequence.StandardKey.Italic,
                                   lambda on: self._merge(italic=on))
        self.underline = self._toggle(bar, "U", "Underline", QKeySequence.StandardKey.Underline,
                                      lambda on: self._merge(underline=on))
        self.strike = self._toggle(bar, "S", "Strikethrough", None,
                                   lambda on: self._merge(strike=on))
        for action, style in ((self.bold, "bold"), (self.italic, "italic"),
                              (self.underline, "underline"), (self.strike, "strike")):
            font = QFont()
            font.setBold(style == "bold")
            font.setItalic(style == "italic")
            font.setUnderline(style == "underline")
            font.setStrikeOut(style == "strike")
            action.setFont(font)

        color = QAction("A", self)
        color.setToolTip("Text colour")
        color.triggered.connect(self._pick_color)
        bar.addAction(color)
        bar.addSeparator()

        bullets = QAction("• List", self)
        bullets.setToolTip("Bulleted list")
        bullets.triggered.connect(lambda: self._toggle_list(QTextListFormat.Style.ListDisc))
        bar.addAction(bullets)
        numbers = QAction("1. List", self)
        numbers.setToolTip("Numbered list")
        numbers.triggered.connect(lambda: self._toggle_list(QTextListFormat.Style.ListDecimal))
        bar.addAction(numbers)
        indent = QAction("→", self)
        indent.setToolTip("Increase indent")
        indent.triggered.connect(lambda: self._indent(+1))
        bar.addAction(indent)
        outdent = QAction("←", self)
        outdent.setToolTip("Decrease indent")
        outdent.triggered.connect(lambda: self._indent(-1))
        bar.addAction(outdent)
        bar.addSeparator()

        clear = QAction("Clear", self)
        clear.setToolTip("Clear character formatting")
        clear.triggered.connect(self._clear_format)
        bar.addAction(clear)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(bar)
        layout.addWidget(self.edit)

        self.edit.currentCharFormatChanged.connect(self._sync_toolbar)
        self.edit.cursorPositionChanged.connect(self._sync_heading)

    def _toggle(self, bar: QToolBar, text: str, tip: str, key, slot: Callable[[bool], None]) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        action.setToolTip(tip)
        if key is not None:
            action.setShortcut(key)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(slot)
        bar.addAction(action)
        self.addAction(action)
        return action

    # ------------------------------------------------------------- content

    def html(self) -> str:
        return self.edit.toHtml()

    def plain_text(self) -> str:
        return self.edit.toPlainText()

    def set_html(self, html: str) -> None:
        self.edit.setHtml(html)
        self.edit.document().setModified(False)

    # ---------------------------------------------------------- formatting

    def _merge(self, *, weight=None, italic=None, underline=None, strike=None, color=None) -> None:
        fmt = QTextCharFormat()
        if weight is not None:
            fmt.setFontWeight(weight)
        if italic is not None:
            fmt.setFontItalic(italic)
        if underline is not None:
            fmt.setFontUnderline(underline)
        if strike is not None:
            fmt.setFontStrikeOut(strike)
        if color is not None:
            fmt.setForeground(color)
        cursor = self.edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self.edit.textColor(), self, "Text colour")
        if color.isValid():
            self._merge(color=color)

    def _clear_format(self) -> None:
        cursor = self.edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.setCharFormat(QTextCharFormat())
        self.edit.setCurrentCharFormat(QTextCharFormat())
        self.edit.setFocus()

    def _selected_blocks_cursor(self) -> QTextCursor:
        """A cursor spanning every block touched by the current selection."""
        cursor = self.edit.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        span = QTextCursor(self.edit.document())
        span.setPosition(start)
        span.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        span.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        span.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        return span

    def _set_heading(self, level: int) -> None:
        span = self._selected_blocks_cursor()
        span.beginEditBlock()
        block_fmt = QTextBlockFormat()
        block_fmt.setHeadingLevel(level)
        span.mergeBlockFormat(block_fmt)
        char_fmt = QTextCharFormat()
        char_fmt.setFontWeight(QFont.Weight.Bold if level else QFont.Weight.Normal)
        # Qt's size adjustment: 0 is normal, +3 is largest.
        char_fmt.setProperty(QTextFormat.Property.FontSizeAdjustment, (4 - level) if level else 0)
        span.mergeCharFormat(char_fmt)
        span.endEditBlock()
        self.edit.mergeCurrentCharFormat(char_fmt)
        self.edit.setFocus()

    def _toggle_list(self, style: QTextListFormat.Style) -> None:
        cursor = self.edit.textCursor()
        current = cursor.currentList()
        cursor.beginEditBlock()
        if current is not None and current.format().style() == style:
            span = self._selected_blocks_cursor()
            block = self.edit.document().findBlock(span.selectionStart())
            while block.isValid() and block.position() <= span.selectionEnd():
                if block.textList() is not None:
                    block.textList().remove(block)
                    c = QTextCursor(block)
                    fmt = block.blockFormat()
                    fmt.setIndent(0)
                    c.setBlockFormat(fmt)
                block = block.next()
        elif current is not None:
            fmt = current.format()
            fmt.setStyle(style)
            current.setFormat(fmt)
        else:
            cursor.createList(style)
        cursor.endEditBlock()
        self.edit.setFocus()

    def _indent(self, delta: int) -> None:
        cursor = self.edit.textCursor()
        current = cursor.currentList()
        if current is not None:
            fmt = QTextListFormat(current.format())
            fmt.setIndent(max(1, fmt.indent() + delta))
            cursor.createList(fmt)
        else:
            span = self._selected_blocks_cursor()
            fmt = QTextBlockFormat()
            fmt.setIndent(max(0, cursor.blockFormat().indent() + delta))
            span.mergeBlockFormat(fmt)
        self.edit.setFocus()

    def _sync_toolbar(self, fmt: QTextCharFormat) -> None:
        self.bold.setChecked(fmt.fontWeight() >= QFont.Weight.Bold)
        self.italic.setChecked(fmt.fontItalic())
        self.underline.setChecked(fmt.fontUnderline())
        self.strike.setChecked(fmt.fontStrikeOut())

    def _sync_heading(self) -> None:
        level = self.edit.textCursor().blockFormat().headingLevel()
        self.heading.setCurrentIndex(level if 0 <= level < len(HEADINGS) else 0)


class ActivityEditor(QWidget):
    """Form for one activity.  Emits `saveRequested` when the user saves."""

    saveRequested = pyqtSignal()
    revertRequested = pyqtSignal()
    dirtyChanged = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._activity: Activity | None = None
        self._dirty = False
        self._loading = False
        self._titles: dict[int, str] = {}

        self.id_label = QLabel("—")
        font = self.id_label.font()
        font.setBold(True)
        self.id_label.setFont(font)

        self.title = QLineEdit()
        self.title.setPlaceholderText("Short title")

        self.duration = QDoubleSpinBox()
        self.duration.setRange(0, 1_000_000)
        self.duration.setDecimals(0)
        self.duration.setSingleStep(1)
        self.duration.setSuffix(" weeks")
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.status = QComboBox()
        self.status.addItems(STATUSES)

        self.owner = QLineEdit()
        self.owner.setPlaceholderText("Who does the work (optional)")

        self.group = QLineEdit()
        self.group.setPlaceholderText("Activity group (optional)")

        self.depends = QLineEdit()
        self.depends.setPlaceholderText("IDs of prerequisite activities, e.g. 3, 7, 12")
        self.depends_hint = QLabel()
        self.depends_hint.setWordWrap(True)
        self.depends_hint.setTextFormat(Qt.TextFormat.PlainText)

        self.required_by = QLabel("—")
        self.required_by.setWordWrap(True)
        self.timestamps = QLabel()
        self.timestamps.setStyleSheet("color: gray;")

        duration_row = QHBoxLayout()
        duration_row.addWidget(self.duration)
        duration_row.addSpacing(16)
        duration_row.addWidget(QLabel("Status:"))
        duration_row.addWidget(self.status)
        duration_row.addStretch(1)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("ID:", self.id_label)
        form.addRow("Title:", self.title)
        form.addRow("Duration:", duration_row)
        form.addRow("Owner:", self.owner)
        form.addRow("Group:", self.group)
        form.addRow("Depends on:", self.depends)
        form.addRow("", self.depends_hint)
        form.addRow("Required by:", self.required_by)

        self.scope = RichTextEditor()
        self.risks = RichTextEditor()
        self.risks.edit.setPlaceholderText("Describe risks for this activity…")
        self.risks.setFixedHeight(180)

        self.save_button = QPushButton("Save Activity")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.saveRequested)
        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(self.revertRequested)
        buttons = QHBoxLayout()
        buttons.addWidget(self.timestamps)
        buttons.addStretch(1)
        buttons.addWidget(self.revert_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Scope of work:"))
        layout.addWidget(self.scope, 1)
        layout.addWidget(QLabel("Risks:"))
        layout.addWidget(self.risks)
        layout.addLayout(buttons)

        self.title.textEdited.connect(self._mark_dirty)
        self.duration.valueChanged.connect(self._mark_dirty)
        self.status.currentIndexChanged.connect(self._mark_dirty)
        self.owner.textEdited.connect(self._mark_dirty)
        self.group.textEdited.connect(self._mark_dirty)
        self.depends.textEdited.connect(self._mark_dirty)
        self.depends.textChanged.connect(self._update_dependency_hint)
        self.scope.textChanged.connect(self._mark_dirty)
        self.risks.textChanged.connect(self._mark_dirty)

        self.load(None)

    # --------------------------------------------------------------- state

    @property
    def activity_id(self) -> int | None:
        return self._activity.id if self._activity else None

    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, dirty: bool) -> None:
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirtyChanged.emit(dirty)
        self.save_button.setEnabled(dirty and self._activity is not None)
        self.revert_button.setEnabled(dirty and self._activity is not None)

    def _mark_dirty(self, *_args) -> None:
        if not self._loading and self._activity is not None:
            self._set_dirty(True)

    def set_context(self, titles: dict[int, str], required_by: list[int]) -> None:
        """Information about the rest of the project, shown read-only."""
        self._titles = titles
        self.required_by.setText(self._describe_ids(required_by) or "—")
        self._update_dependency_hint()

    def load(self, activity: Activity | None) -> None:
        self._loading = True
        try:
            self._activity = activity
            enabled = activity is not None
            for w in (self.title, self.duration, self.status, self.owner, self.group, self.depends, self.scope, self.risks):
                w.setEnabled(enabled)
            a = activity or Activity()
            self.id_label.setText(str(a.id) if a.id is not None else "—")
            self.title.setText(a.title)
            self.duration.setValue(a.duration_weeks)
            idx = self.status.findText(a.status)
            self.status.setCurrentIndex(idx if idx >= 0 else 0)
            self.owner.setText(a.owner)
            self.group.setText(a.group_name)
            self.depends.setText(format_dependency_ids(a.depends_on))
            self.scope.set_html(a.description_html)
            self.risks.set_html(a.risks_html)
            if activity is None:
                self.timestamps.setText("Select an activity, or create one with Activity ▸ New.")
                self.required_by.setText("—")
            else:
                self.timestamps.setText(
                    f"Created {a.created_at.replace('T', ' ')} · "
                    f"updated {a.updated_at.replace('T', ' ')}"
                )
        finally:
            self._loading = False
        self._set_dirty(False)
        self._update_dependency_hint()

    def to_activity(self) -> Activity:
        """The activity as currently edited.  Raises ValueError on bad dependency text."""
        assert self._activity is not None
        return Activity(
            id=self._activity.id,
            title=self.title.text().strip(),
            description_html=self.scope.html() if self.scope.plain_text().strip() else "",
            description_text=self.scope.plain_text(),
            risks_html=self.risks.html() if self.risks.plain_text().strip() else "",
            risks_text=self.risks.plain_text(),
            duration_weeks=self.duration.value(),
            status=self.status.currentText(),
            owner=self.owner.text().strip(),
            group_name=self.group.text().strip(),
            depends_on=parse_dependency_ids(self.depends.text()),
            created_at=self._activity.created_at,
            updated_at=self._activity.updated_at,
        )

    def focus_title(self) -> None:
        self.title.setFocus()
        self.title.selectAll()

    def show_dependency_error(self, message: str) -> None:
        self.depends_hint.setText(message)
        self.depends_hint.setStyleSheet("color: #c0392b;")
        self.depends.setFocus()

    # ------------------------------------------------------------- helpers

    def _describe_ids(self, ids: list[int]) -> str:
        parts = []
        for i in ids:
            title = self._titles.get(i)
            parts.append(f"{i} – {title}" if title else f"{i} (unknown)")
        return "; ".join(parts)

    def _update_dependency_hint(self) -> None:
        try:
            ids = parse_dependency_ids(self.depends.text())
        except ValueError as exc:
            self.depends_hint.setText(str(exc))
            self.depends_hint.setStyleSheet("color: #c0392b;")
            return
        unknown = [i for i in ids if i not in self._titles]
        self.depends_hint.setText(self._describe_ids(ids))
        self.depends_hint.setStyleSheet("color: #c0392b;" if unknown else "color: gray;")
