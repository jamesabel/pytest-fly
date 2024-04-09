import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from datetime import datetime
import numpy as np

from .db import get_most_recent_run_info, RunInfo


def visualize():
    run_info = get_most_recent_run_info()

    root = tk.Tk()
    root.title("Test Phases Timeline")

    fig = Figure(figsize=(10, 6), dpi=100)
    plot_timeline(run_info, fig)

    canvas = FigureCanvasTkAgg(fig, master=root)  # A tk.DrawingArea
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    tk.mainloop()


def plot_timeline(data: dict[str, dict[str, RunInfo]], fig):

    # sort the data
    data = dict(sorted(data.items(), key=lambda x: x[0], reverse=True))

    ax = fig.add_subplot(111)  # Create a subplot in the figure

    # Rest of the plotting logic remains the same as before, just use `fig` and `ax` instead of `plt`
    workers = set(info.worker_id for test in data.values() for info in test.values())
    colors = plt.cm.jet(np.linspace(0, 1, len(workers)))
    worker_colors = dict(zip(workers, colors))

    yticks, yticklabels = [], []
    for i, (test_name, phases) in enumerate(data.items()):
        for phase_name, phase_info in phases.items():
            start_time = datetime.fromtimestamp(phase_info.start)
            end_time = datetime.fromtimestamp(phase_info.stop)
            worker_id = phase_info.worker_id

            ax.plot([start_time, end_time], [i, i], color=worker_colors[worker_id], marker='o', markersize=4,
                    label=worker_id if phase_name == 'setup' else "")
            yticks.append(i)
            yticklabels.append(f"{test_name}")

    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels)
    ax.xaxis.set_major_locator(mdates.MinuteLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax.set_xlabel('Time')
    ax.set_ylabel('Test Phases')
    ax.set_title('Timeline of Test Phases per Worker')
    ax.grid(True)

    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), title="Workers")
