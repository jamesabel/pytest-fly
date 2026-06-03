"""Modal dialog that guides the user to set a valid Target Project Path (the program under test).

The PUT path is a stored preference, so it can point at a directory that no longer exists — a
moved or deleted project, or a mistyped ``--target``.  pytest-fly collects the tests it runs from
this path, so an invalid one would otherwise yield a silent, empty, confusing run.  This dialog
surfaces the problem and walks the user through choosing a real directory before any run proceeds.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..logger import get_logger
from ..preferences import get_active_put_path, set_active_put_path

log = get_logger()


class TargetProjectPathDialog(QDialog):
    """Prompt for an existing directory to use as the Target Project Path.

    The OK button stays disabled until the entered/browsed path is an existing directory, so the
    dialog can only resolve to a usable PUT.  Accepting persists the choice via
    :func:`set_active_put_path`.
    """

    def __init__(self, missing_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Target Project Path Not Found")
        self.setModal(True)
        self._selected_path: Path | None = None

        layout = QVBoxLayout(self)

        message = QLabel(
            f"The configured target project path does not exist:\n\n{missing_path}\n\n"
            "pytest-fly runs the tests found in this directory. Choose the project directory "
            "(or a subdirectory such as 'tests') whose tests you want to run."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        row = QHBoxLayout()
        self.path_lineedit = QLineEdit(str(missing_path))
        self.path_lineedit.textChanged.connect(self._validate)
        row.addWidget(self.path_lineedit)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse)
        row.addWidget(self.browse_button)
        layout.addLayout(row)

        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: #b22222;")
        layout.addWidget(self.validation_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._validate(self.path_lineedit.text())

    def _browse(self):
        """Open a directory picker, seeded from the current text (or the user's home)."""
        start = self.path_lineedit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Select target project directory", start)
        if selected:
            self.path_lineedit.setText(selected)

    def _validate(self, text: str) -> bool:
        """Enable OK only for an existing directory; show a hint otherwise."""
        candidate = text.strip()
        ok = bool(candidate) and Path(candidate).is_dir()
        self.validation_label.setText("" if ok else "Enter or browse to an existing directory.")
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        return ok

    def _on_accept(self):
        """Persist the chosen path and close, if it is a valid directory."""
        text = self.path_lineedit.text().strip()
        if not self._validate(text):
            return
        self._selected_path = Path(text).resolve()
        set_active_put_path(self._selected_path)
        log.info(f"target project path set to: {self._selected_path}")
        self.accept()

    def selected_path(self) -> Path | None:
        """Return the persisted path after an accepted dialog, else ``None``."""
        return self._selected_path


def ensure_valid_target_project_path(parent: QWidget | None = None) -> Path | None:
    """Return a usable Target Project Path, prompting the user if the configured one is missing.

    When the configured PUT is an existing directory it is returned directly (no dialog).
    Otherwise a guided :class:`TargetProjectPathDialog` is shown; this returns the newly chosen
    (and persisted) path, or ``None`` if the user cancels.
    """
    put_path = get_active_put_path()
    if put_path.is_dir():
        return put_path
    log.warning(f"configured target project path does not exist: {put_path}")
    dialog = TargetProjectPathDialog(put_path, parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_path()
    return None
