from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.geometry import Size
from rich.segment import Segment


def create_unicode_bar(value: float, length: int) -> str:
    """
    Create a high-resolution Unicode bar.

    Args:
        value (float): A value between 0 and 1 indicating the bar's fill level.
        length (int): The total number of characters in the bar.

    Returns:
        str: The Unicode bar as a string.
    """

    value = max(0.0, min(value, 1.0))  # Ensure value is clamped between 0 and 1

    # determine the number of full blocks and the fraction of the partial block
    blocks_real = value * length / 2
    full_blocks = int(blocks_real)
    partial_block_fraction = blocks_real - full_blocks

    # Select the correct character for the partial block
    left_half_block = "\u258C"
    full_block = "\u2588"
    if partial_block_fraction >= 0.75:
        partial_block = full_block
    elif partial_block_fraction >= 0.25:
        partial_block = left_half_block
    else:
        partial_block = ""

    # Create the bar
    bar = full_block * full_blocks + partial_block
    bar += " " * (length - len(bar))  # Pad with spaces to ensure fixed length
    return bar


class HorizontalBarGraph(ScrollView):
    """A horizontal bar graph with X and Y axes, gridlines, and labels."""

    data = {f"Item {i}": i for i in range(0, 50)}

    def render(self):
        max_value = max(self.data.values())
        graph = ""

        # Create the graph row by row
        for label, value in self.data.items():
            bar = create_unicode_bar(value / float(max_value), max_value)
            graph += f"{label:8} | {bar} ({value})\n"

        # Add the X-axis at the bottom
        graph += "         +" + "-" * (max_value + 2) + "\n"
        graph += "           " + "".join(f"{i:<2}" for i in range(1, max_value + 1))

        return graph  # Return the graph as a string


class Running(ScrollView):

    def __init__(self):
        super().__init__()
        self.virtual_size = Size(100, 100)

    def render_line(self, line: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        lines = [Segment(f"{line+scroll_y}")]
        strip = Strip(lines)
        # strip = strip.crop(scroll_x, scroll_x + self.size.width)
        return strip


class VisualizationTextual(App):
    # CSS = """
    # ScrollView {
    #     width: 50%;
    #     height: 100%;
    # }
    # """

    def compose(self) -> ComposeResult:
        # Create the layout with two sections
        with Horizontal():
            yield HorizontalBarGraph()
            yield Running()


def visualize_textual():
    app = VisualizationTextual()
    app.run()
