"""
Capture screenshots and an animated GIF for the README.

Drives the pytest-fly GUI in-process against the demo test suite, samples the Run
tab into GIF frames during the run, then switches through every tab to grab a
PNG once the run is complete.

Usage (from the repo root):

    pip install -r requirements-dev.txt
    python scripts/capture_assets.py

Outputs:
    docs/images/run.png
    docs/images/graph.png
    docs/images/table.png
    docs/images/coverage.png
    docs/images/configuration.png
    docs/images/about.png
    docs/images/run_animation.gif
"""

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from PIL import Image  # noqa: E402  (sys.path mutation above is intentional)
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from demo.demo import generate_tests  # noqa: E402
from pytest_fly.gui.gui_main import FlyAppMainWindow  # noqa: E402
from pytest_fly.preferences import get_pref  # noqa: E402

WINDOW_SIZE = (1280, 800)
GIF_SAMPLE_INTERVAL_MS = 600
GIF_FRAME_DURATION_MS = 600
GIF_MAX_BYTES = 2 * 1024 * 1024  # 2 MB target ceiling
TAB_SETTLE_DELAY_MS = 400
POST_RUN_SETTLE_DELAY_MS = 1500
RUN_TRIGGER_DELAY_MS = 800

TAB_FILENAMES = ["run", "graph", "table", "coverage", "configuration", "about"]


def qpixmap_to_pil(pixmap: QPixmap) -> Image.Image:
    """Convert a QPixmap to a PIL RGBA image, accounting for QImage row padding."""
    qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width = qimage.width()
    height = qimage.height()
    bytes_per_line = qimage.bytesPerLine()
    raw = bytes(qimage.constBits())
    row_bytes = width * 4
    if bytes_per_line == row_bytes:
        return Image.frombytes("RGBA", (width, height), raw)
    # Strip per-row padding before handing to Pillow.
    rows = [raw[i * bytes_per_line : i * bytes_per_line + row_bytes] for i in range(height)]
    return Image.frombytes("RGBA", (width, height), b"".join(rows))


class Capturer:
    """State machine that samples GIF frames during the run and grabs per-tab PNGs after."""

    def __init__(self, window: FlyAppMainWindow, output_dir: Path):
        self.window = window
        self.output_dir = output_dir
        self.gif_frames: list[Image.Image] = []
        self.saw_running = False

        self.gif_timer = QTimer(window, interval=GIF_SAMPLE_INTERVAL_MS)
        self.gif_timer.timeout.connect(self._sample_gif_frame)

        self.done_timer = QTimer(window, interval=500)
        self.done_timer.timeout.connect(self._check_done)

    def start(self):
        self.gif_timer.start()
        self.done_timer.start()

    def _runner(self):
        return self.window.run_tab.control_window.pytest_runner

    def _sample_gif_frame(self):
        # Skip frames before the run starts to avoid 30+ frames of an empty Run tab.
        if not self.saw_running:
            return
        pix = self.window.run_tab.grab()
        self.gif_frames.append(qpixmap_to_pil(pix))

    def _check_done(self):
        runner = self._runner()
        if runner is None:
            return
        if runner.is_running():
            self.saw_running = True
            return
        if self.saw_running:
            # Capture one final frame so the GIF ends on the completed state.
            self._sample_gif_frame()
            self.gif_timer.stop()
            self.done_timer.stop()
            QTimer.singleShot(POST_RUN_SETTLE_DELAY_MS, self._capture_tabs)

    def _capture_tabs(self):
        self._capture_tab_index(0)

    def _capture_tab_index(self, idx: int):
        if idx >= len(TAB_FILENAMES):
            self._stitch_gif()
            QApplication.instance().quit()
            return
        self.window.tab_widget.setCurrentIndex(idx)
        QApplication.processEvents()

        def _grab_and_advance():
            widget = self.window.tab_widget.currentWidget()
            pix = widget.grab()
            out_path = self.output_dir / f"{TAB_FILENAMES[idx]}.png"
            pix.save(str(out_path), "PNG")
            print(f"  wrote {out_path.name} ({out_path.stat().st_size // 1024} KB)")
            self._capture_tab_index(idx + 1)

        QTimer.singleShot(TAB_SETTLE_DELAY_MS, _grab_and_advance)

    def _save_gif(self, frames: list[Image.Image], path: Path):
        frames[0].save(
            str(path),
            save_all=True,
            append_images=frames[1:],
            duration=GIF_FRAME_DURATION_MS,
            loop=0,
            optimize=True,
        )

    def _stitch_gif(self):
        if not self.gif_frames:
            print("  no GIF frames captured (run never started?)")
            return
        gif_path = self.output_dir / "run_animation.gif"
        self._save_gif(self.gif_frames, gif_path)
        size = gif_path.stat().st_size
        print(f"  wrote {gif_path.name} ({size // 1024} KB, {len(self.gif_frames)} frames)")

        if size > GIF_MAX_BYTES:
            print(f"  GIF exceeds {GIF_MAX_BYTES // 1024} KB target; downscaling 75% + 128-color quantize")
            scaled: list[Image.Image] = []
            for f in self.gif_frames:
                small = f.resize((int(f.width * 0.75), int(f.height * 0.75)))
                scaled.append(small.quantize(colors=128))
            self._save_gif(scaled, gif_path)
            size = gif_path.stat().st_size
            print(f"  rewrote {gif_path.name} ({size // 1024} KB)")


def main():
    output_dir = REPO_ROOT / "docs" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate the demo test suite into ./fly_demo (under the repo root).
    os.chdir(REPO_ROOT)
    generate_tests()
    fly_demo_dir = (REPO_ROOT / "fly_demo").resolve()

    # Use a throwaway data dir so screenshots aren't polluted by prior local runs.
    data_dir = Path(tempfile.mkdtemp(prefix="pytest_fly_capture_"))
    print(f"capture data dir: {data_dir}")
    print(f"target project: {fly_demo_dir}")

    # Point the GUI at the demo dir for this run, restoring the user's saved value on exit so
    # the capture doesn't permanently mutate their preferences.
    pref = get_pref()
    saved_target = pref.target_project_path
    pref.target_project_path = str(fly_demo_dir)

    try:
        app = QApplication.instance() or QApplication([])
        window = FlyAppMainWindow(data_dir)
        window.resize(*WINDOW_SIZE)
        window.show()

        capturer = Capturer(window, output_dir)
        QTimer.singleShot(RUN_TRIGGER_DELAY_MS, window.run_tab.control_window.run)
        QTimer.singleShot(RUN_TRIGGER_DELAY_MS + 100, capturer.start)

        app.exec()
    finally:
        pref.target_project_path = saved_target

    print("done.")


if __name__ == "__main__":
    main()
