import csv
from pathlib import Path


def csv_dump(run_infos: dict, csv_file_path: Path):

    csv_file_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_file_path.open("w", newline="") as csv_file:
        headers = ["test", "phase", "worker_id", "start", "stop", "passed"]
        csv_writer = csv.DictWriter(csv_file, headers)
        csv_writer.writeheader()
        for test, test_info in run_infos.items():
            for phase, run_info in test_info.items():
                row = {"test": test, "phase": phase, "worker_id": run_info.worker_id, "start": run_info.start, "stop": run_info.stop, "passed": run_info.passed}
                csv_writer.writerow(row)
