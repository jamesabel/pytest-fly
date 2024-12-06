import time
from copy import deepcopy

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel


class RunningWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Running")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.running_text_label = QLabel("Initializing ...")
        layout.addWidget(self.running_text_label)

    def update_window(self, run_infos: dict):
        run_infos = deepcopy(run_infos)
        most_recent_states = {}
        for test in sorted(run_infos):
            test_data = run_infos[test]
            times = sorted(zip(test_data, test_data.values()), key=lambda x: x[1].stop)
            most_recent_states[test] = times[-1]
        running_tests = []
        for test, times in most_recent_states.items():
            if times[0] != "teardown" or times[1].stop is None:
                run_time = time.time() - times[1].start
                running_tests.append(f"{test} ({run_time:.2f}s)")
        if len(running_tests) > 0:
            self.running_text_label.setText("\n".join(running_tests))
        else:
            self.running_text_label.setText("(no tests currently running)")


class TestListWindow(QGroupBox):

    def __init__(self):
        self.count = 0
        super().__init__()
        self.setTitle("Tests")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.running_text_label = QLabel("Initializing ...")
        layout.addWidget(self.running_text_label)

    def update_window(self, run_infos: dict):

        run_infos = deepcopy(run_infos)
        test_states = {}
        for test, test_data in run_infos.items():
            start = None
            stop = None
            for phase, run_info in test_data.items():
                if run_info.start is not None and (start is None or run_info.start < start):
                    start = run_info.start
                if run_info.stop is not None and (stop is None or run_info.stop > stop):
                    stop = run_info.stop
            if start is not None and stop is not None and stop > start:
                test_states[test] = stop - start
            else:
                test_states[test] = None

        lines = []
        for test in sorted(test_states):
            if (test_duration := test_states[test]) is None:
                lines.append(f"{test},running")
            else:
                lines.append(f"{test},{test_duration:.2f}")

        filled_block = "█"
        blink = filled_block if self.count % 2 == 0 else " "
        lines.append(f"{blink}")
        self.running_text_label.setText("\n".join(lines))
        self.count += 1


class StatusWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.running_window = RunningWindow()
        self.test_list_window = TestListWindow()
        layout.addWidget(self.running_window)
        layout.addWidget(self.test_list_window)
        layout.addStretch()

    def update_window(self, run_infos: dict):
        self.running_window.update_window(run_infos)
        self.test_list_window.update_window(run_infos)
