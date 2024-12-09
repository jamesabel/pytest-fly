from textual.app import App, ComposeResult
from textual.containers import Horizontal


from .bar_chart_window import BarChart
from .status_window import StatusWindow


class VisualizationTextual(App):

    # CSS = """
    # #main-content {
    #     width: 100%; /* Occupy the entire horizontal space */
    #     text-align: left;
    # }
    # """

    def compose(self) -> ComposeResult:
        # Create the layout with two sections
        with Horizontal():
            yield BarChart()
            # yield StatusWindow()


def visualize_textual():
    app = VisualizationTextual()
    app.run()
