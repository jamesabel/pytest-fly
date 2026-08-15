"""
Reorderable, per-row-checkable list widget for the test-ordering aspects.

Extracted from the Configuration tab module: this is a self-contained widget with its
own layout-measurement logic, unrelated to the preference form that hosts it.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStyle, QVBoxLayout, QWidget

from pytest_fly.interfaces import OrderingAspect
from pytest_fly.preferences import get_ordering_aspects_ordered, set_ordering_aspects_ordered

_ordering_aspect_labels: dict[OrderingAspect, str] = {
    OrderingAspect.FAILED_FIRST: "Failed tests",
    OrderingAspect.NEVER_RUN_FIRST: "Never-run tests",
    OrderingAspect.LONGEST_PRIOR_FIRST: "Longest prior execution time",
    OrderingAspect.COVERAGE_EFFICIENCY: "Coverage efficiency (lines/sec)",
}

_ordering_aspect_tooltips: dict[OrderingAspect, str] = {
    OrderingAspect.FAILED_FIRST: "Tests that failed in the previous run run first. Tests with no prior record tie for last.",
    OrderingAspect.NEVER_RUN_FIRST: "Tests with no record in the database (any program-under-test version) run first.",
    OrderingAspect.LONGEST_PRIOR_FIRST: (
        "Tests with the longest prior passing-run duration run first. Helps parallel runs by starting the\n"
        "critical-path tests earliest; shorter tests backfill the remaining workers. Tests with no prior\n"
        "duration tie for last."
    ),
    OrderingAspect.COVERAGE_EFFICIENCY: "Tests with the highest lines-covered-per-second run first. Requires prior duration and coverage data; tests missing either tie for last.",
}


class OrderingAspectsWidget(QGroupBox):
    """Reorderable, per-row-checkable list of test-ordering aspects."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Test Ordering (highest priority=top)", parent)
        # Hug our content — do not stretch into parent layout whitespace.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip(
            "Controls the order tests run in.\n\n"
            "Check a row to enable that aspect; uncheck to disable. Enabled rows appear above disabled ones.\n"
            "Position sets priority — the topmost enabled row is the primary sort; rows below it break ties.\n"
            "Use Up / Down to reorder the selected row.\n\n"
            "Failed tests: previously-failed tests run before previously-passed ones.\n"
            "Never-run tests: tests with no record in the database run before tests that have run before.\n"
            "Longest prior execution time: slowest passing tests run first — helps parallel runs by starting\n"
            "the critical path earliest so short tests backfill the remaining workers.\n"
            "Coverage efficiency: tests with the highest lines-covered-per-second run first.\n\n"
            "All aspects apply in every run mode, including Restart — prior-run data shapes execution order,\n"
            "not which tests run. Tests missing the data an aspect needs tie for last under that aspect.\n"
            "Singleton tests always run last regardless of these settings."
        )

        outer = QVBoxLayout()
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        outer.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setLayout(outer)

        body = QHBoxLayout()
        body.setSpacing(4)
        body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        outer.addLayout(body)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # Remove the scroll bars — with only four fixed rows the widget is sized
        # to show them all, so scrolling would be misleading whitespace.
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self._list)

        buttons = QVBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignTop)
        buttons.setSpacing(2)
        self._up_button = QPushButton("Up")
        self._up_button.clicked.connect(lambda: self._move_selected(-1))
        buttons.addWidget(self._up_button)
        self._down_button = QPushButton("Down")
        self._down_button.clicked.connect(lambda: self._move_selected(1))
        buttons.addWidget(self._down_button)
        body.addLayout(buttons)

        self._populate_from_prefs()
        self._resize_list_to_content()
        # Connect after populating so setCheckState during populate does not
        # fire the persistence slot.
        self._list.itemChanged.connect(self._on_item_changed)

    def _resize_list_to_content(self) -> None:
        """Fix the list widget's size to exactly fit its rows and longest label.

        Sized from the actual rendered text bounding box (not just glyph
        advance) plus the space the style needs for the check indicator and
        item margins.  The components are deliberately over-measured: Qt's
        reported ``PM_IndicatorWidth`` under-counts on Windows (returns ~14 px
        for a visibly ~20 px box) and ``horizontalAdvance`` under-counts when
        ClearType widens glyphs.  The goal is a list that's just wider than
        needed — never narrower.
        """
        count = self._list.count()
        if count == 0:
            return
        fm = self._list.fontMetrics()
        # Take the larger of horizontalAdvance and boundingRect — the latter
        # wins for glyphs that extend past their advance (italic f, descenders).
        text_width = max(max(fm.horizontalAdvance(_ordering_aspect_labels[a]), fm.boundingRect(_ordering_aspect_labels[a]).width()) for a in _ordering_aspect_labels)
        # Style-reported components:
        style = self._list.style()
        indicator = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, self._list)
        # PM_ScrollBarExtent: even though the scroll bars are turned off, some
        # item-view metrics reserve the extent in their layout calculations.
        scroll_extent = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self._list)
        frame = 2 * self._list.frameWidth()
        # Slack: left/right item margins, indicator-to-text gap, plus general safety.
        # Kept generous because ClearType/DirectWrite render text a few percent wider
        # than ``QFontMetrics.horizontalAdvance`` predicts.  Expressed in character
        # widths (not fixed pixels) so it tracks the font size and DPI scaling.
        slack = 4 * fm.horizontalAdvance("X")
        width = text_width + indicator + scroll_extent + slack + frame
        row_height = self._list.sizeHintForRow(0) or fm.height() + 4
        self._list.setFixedSize(width, row_height * count + frame)

    def _populate_from_prefs(self) -> None:
        """Render enabled aspects (in priority order) first, then disabled aspects in enum order."""
        self._list.clear()
        enabled = get_ordering_aspects_ordered()
        disabled = [a for a in OrderingAspect if a not in enabled]
        for aspect in list(enabled) + disabled:
            item = QListWidgetItem(_ordering_aspect_labels[aspect])
            item.setToolTip(_ordering_aspect_tooltips[aspect])
            item.setData(Qt.ItemDataRole.UserRole, aspect.value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if aspect in enabled else Qt.CheckState.Unchecked)
            self._list.addItem(item)

    def _move_selected(self, delta: int) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(new_row, item)
        self._list.setCurrentRow(new_row)
        self._persist()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Keep enabled rows above disabled rows when the user toggles a checkbox.

        Unchecking a row drops it to the bottom of the list; checking a row
        promotes it to the end of the enabled group (just above the first
        disabled row).  Always persists.
        """
        current = self._list.row(item)
        if item.checkState() == Qt.CheckState.Checked:
            # Target row: first unchecked row above the current position,
            # i.e. the insertion point at the end of the enabled group.
            target = current
            for i in range(current):
                if self._list.item(i).checkState() != Qt.CheckState.Checked:
                    target = i
                    break
            else:
                target = current  # already at/after the last checked row
        else:
            target = self._list.count() - 1  # move to the very end

        if target != current:
            # Signals block prevents _on_item_changed from re-entering while
            # the row is moved programmatically.
            self._list.blockSignals(True)
            taken = self._list.takeItem(current)
            self._list.insertItem(target, taken)
            self._list.setCurrentRow(target)
            self._list.blockSignals(False)

        self._persist()

    def _persist(self) -> None:
        enabled: list[OrderingAspect] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                try:
                    enabled.append(OrderingAspect(item.data(Qt.ItemDataRole.UserRole)))
                except ValueError:
                    continue
        set_ordering_aspects_ordered(enabled)
