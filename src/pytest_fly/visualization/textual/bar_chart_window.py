import time

from textual.scroll_view import ScrollView

from .block_bar import create_text_bar
from ...db import get_most_recent_run_info
from ..visualization_calculations import VisualizationCalculations


class BarChart(ScrollView):

    def __init__(self):
        self.render_time = 0.0  # seconds
        super().__init__()

    def render(self):

        start = time.time()
        run_infos = get_most_recent_run_info()
        visualization_calculations = VisualizationCalculations(run_infos)

        y_labels = {}
        for i, (test_name, phases) in enumerate(visualization_calculations.sorted_data.items()):
            for phase_name, phase_info in phases.items():
                y_labels[test_name] = f"{test_name} ({phase_name})"
        if len(y_labels) > 0:
            max_y_label_width = max(len(label) for label in y_labels.values())
        else:
            max_y_label_width = 1
        max_duration = visualization_calculations.latest_stop - visualization_calculations.earliest_start

        graph = ""
        for i, (test_name, phases) in enumerate(visualization_calculations.sorted_data.items()):
            relative_start = None
            relative_stop = None
            for phase_name, phase_info in phases.items():
                if relative_start is None:
                    relative_start = phase_info.start - visualization_calculations.earliest_start
                else:
                    relative_start = min(relative_start, phase_info.start - visualization_calculations.earliest_start)
                if relative_stop is None:
                    relative_stop = phase_info.stop - visualization_calculations.earliest_start
                else:
                    relative_stop = max(relative_stop, phase_info.stop - visualization_calculations.earliest_start)

            # worker_id = phase_info.worker_id

            duration = relative_stop - relative_start
            padding = 20  # SWAG
            full_bar_width = max(0, self.size.width - max_y_label_width - padding)
            y_label = y_labels[test_name]
            y_label_margin = " " * (max_y_label_width - len(y_label))
            bar_string = create_text_bar(full_bar_width, relative_start / max_duration, duration / max_duration, True, True)

            graph += f"{y_label}{y_label_margin}: {bar_string} {duration:6.1f}\n"
        self.render_time = time.time() - start

        return graph  # Return the graph as a string
