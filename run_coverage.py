"""Run tests with coverage and generate an HTML report."""

import subprocess
import sys
import webbrowser
from pathlib import Path


def main():
    python = sys.executable

    print("Running tests with coverage...")
    result = subprocess.run([python, "-m", "coverage", "run", "--source=src", "-m", "pytest", "tests/", "-q"], cwd=str(Path(__file__).parent))

    print("\nGenerating HTML report...")
    subprocess.run([python, "-m", "coverage", "html", "--directory=htmlcov"], cwd=str(Path(__file__).parent))

    print("\nSummary:")
    subprocess.run([python, "-m", "coverage", "report", "--sort=cover"], cwd=str(Path(__file__).parent))

    index = Path(__file__).parent / "htmlcov" / "index.html"
    if index.exists():
        print(f"\nOpening {index}")
        webbrowser.open(index.as_uri())

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
