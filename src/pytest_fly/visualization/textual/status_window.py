from rich.segment import Segment
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip


class StatusWindow(ScrollView):

    def __init__(self):
        super().__init__()
        self.virtual_size = Size(10, 10)

    def render_line(self, line: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        lines = [Segment(f"{line+scroll_y}")]
        width = self.size.width
        height = self.size.height
        lines = [Segment(f"{line=},{height=},{width=}")]
        strip = Strip(lines)
        # strip = strip.crop(scroll_x, scroll_x + self.size.width)
        return strip
