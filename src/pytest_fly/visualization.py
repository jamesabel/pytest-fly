import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from datetime import datetime
import numpy as np
from typing import Dict

from .db import get_most_recent_run_info, RunInfo
from .utilization import calculate_utilization


def visualize():
    run_info = get_most_recent_run_info()

    utilization, overall_utilization = calculate_utilization(run_info)
    print(f"{utilization=}")
    print(f"{overall_utilization=}")

    root = tk.Tk()
    root.title("Test Phases Timeline")

    fig = Figure(figsize=(10, 6), dpi=100)
    plot_timeline(run_info, fig)

    canvas = FigureCanvasTkAgg(fig, master=root)  # A tk.DrawingArea
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    tk.mainloop()


def plot_timeline(data: Dict[str, Dict[str, RunInfo]], fig: plt.Figure) -> None:
    ax = fig.add_subplot(111)

    # Sort the data by test names in reverse order before plotting
    sorted_data = dict(sorted(data.items(), key=lambda x: x[0], reverse=True))

    worker_utilization, overall_utilization = calculate_utilization(sorted_data)

    # Determine the earliest start time across all tests
    earliest_start = min(phase.start for test in sorted_data.values() for phase in test.values())

    workers = set(info.worker_id for test in sorted_data.values() for info in test.values())
    colors = plt.cm.jet(np.linspace(0, 1, len(workers)))  # Color map for workers
    worker_colors = dict(zip(workers, colors))  # Assign colors to workers

    yticks, yticklabels = [], []
    for i, (test_name, phases) in enumerate(sorted_data.items()):
        for phase_name, phase_info in phases.items():
            # Adjust times to be relative to the earliest start time
            relative_start = phase_info.start - earliest_start
            relative_stop = phase_info.stop - earliest_start
            worker_id = phase_info.worker_id

            # Plot with worker-specific color
            ax.plot([relative_start, relative_stop], [i, i], color=worker_colors[worker_id], marker='o', markersize=4,
                    label=worker_id if phase_name == 'setup' else "")

            if phase_name == list(phases.keys())[0]:
                yticks.append(i)
                yticklabels.append(test_name)

    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels)
    ax.set_xlabel('Time (seconds)')
    ax.set_ylabel('Test Names')
    ax.set_title('Timeline of Test Phases per Worker')
    ax.grid(True)

    # Display overall utilization
    ax.text(1.0, 1.02, f"Overall Utilization: {overall_utilization:.2%}", transform=ax.transAxes, horizontalalignment='right')

    # Display per-worker utilization in text
    text_position = 1.05
    for worker, utilization in worker_utilization.items():
        ax.text(1.0, text_position, f"{worker}: {utilization:.2%}", transform=ax.transAxes, horizontalalignment='right')
        text_position += 0.03  # Adjust text spacing

    # Legend on the right
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), title="Workers", loc='upper left', bbox_to_anchor=(1.05, 1))

    plt.subplots_adjust(right=0.75)  # Adjust subplot to make room for the legend



