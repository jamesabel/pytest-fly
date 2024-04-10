import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np
from typing import Dict
from pathlib import Path

from .db import get_most_recent_run_info, RunInfo
from .utilization import calculate_utilization


def visualize(plot_file_path: Path | None = None) -> None:
    """
    Visualize a timeline of test phases per worker.
    :param plot_file_path: Path to save the plot to.
    """
    run_info = get_most_recent_run_info()

    root = tk.Tk()
    root.title("Test Phases Timeline")

    fig, ax = plt.subplots(figsize=(20, 3 + len(run_info) * 0.5))  # Dynamic height based on the number of tests
    _plot_timeline(run_info, fig, ax, plot_file_path)

    canvas = FigureCanvasTkAgg(fig, master=root)  # A tk.DrawingArea
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    tk.mainloop()


def _plot_timeline(data: Dict[str, Dict[str, RunInfo]], fig, ax, plot_file_path: Path | None) -> None:
    """
    Plot a timeline of test phases per worker.
    :param data: Dictionary with test names as keys and dictionaries with phase names as keys and RunInfo objects as values.
    :param fig: Matplotlib figure object.
    :param ax: Matplotlib axis object.
    :param plot_file_path: Path to save the plot to.
    """
    sorted_data = dict(sorted(data.items(), key=lambda x: x[0], reverse=True))
    worker_utilization, overall_utilization = calculate_utilization(sorted_data)
    earliest_start = min(phase.start for test in sorted_data.values() for phase in test.values())

    workers = set(info.worker_id for test in sorted_data.values() for info in test.values())
    colors = plt.cm.jet(np.linspace(0, 1, len(workers)))
    worker_colors = dict(zip(workers, colors))

    yticks, yticklabels = [], []
    for i, (test_name, phases) in enumerate(sorted_data.items()):
        for phase_name, phase_info in phases.items():
            relative_start = phase_info.start - earliest_start
            relative_stop = phase_info.stop - earliest_start
            worker_id = phase_info.worker_id

            ax.plot([relative_start, relative_stop], [i, i], color=worker_colors[worker_id], marker="o", markersize=4, label=worker_id if phase_name == "setup" else "")

            if phase_name == list(phases.keys())[0]:
                yticks.append(i)
                yticklabels.append(test_name)

    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels)
    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel("Test Names")
    ax.set_title("Timeline of Test Phases per Worker")
    ax.grid(True)

    ax.text(1.0, 1.02, f"Overall Utilization: {overall_utilization:.2%}", transform=ax.transAxes, horizontalalignment="right", fontsize=9)
    text_position = 1.05
    for worker, utilization in worker_utilization.items():
        ax.text(1.0, text_position, f"{worker}: {utilization:.2%}", transform=ax.transAxes, horizontalalignment="right", fontsize=9)
        text_position += 0.03

    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    legend = ax.legend(by_label.values(), by_label.keys(), title="Workers", loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)

    plt.subplots_adjust(right=0.9)  # Make space for the legend

    # Use bbox_extra_artists to include the legend in the tight layout calculation
    if plot_file_path is not None:
        plot_file_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_file_path, bbox_extra_artists=[legend])

    # plt.show()
