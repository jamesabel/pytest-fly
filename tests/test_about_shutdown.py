"""About tab thread teardown — destroying a running QThread is a Qt fatal abort."""

from pytest_fly.gui.about_tab.about import About

from .paths import get_temp_dir


def test_about_shutdown_stops_data_thread(app, qtbot):
    """shutdown() must leave the data thread finished, however early it is called.

    Without it, closing the app before the About data arrived (git-based PUT detection can
    take seconds) destroyed a running QThread: "QThread: Destroyed while thread is still
    running", exit 0xC0000409, no Python traceback.
    """
    about = About(None, get_temp_dir("test_about_shutdown"))
    qtbot.addWidget(about)

    about.shutdown()  # immediately — the worker may still be mid-detect_put_version

    assert not about._thread.isRunning()
    # Idempotent: a second call (e.g. two close paths) is a no-op.
    about.shutdown()
    assert not about._thread.isRunning()
