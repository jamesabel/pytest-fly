from pathlib import Path
import tomllib
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class ProjectInfo:
    application_name: str
    author: str
    version: str

    def __str__(self):
        return f"{self.application_name}\n{self.version}\n{self.author}"


@cache
def get_project_info() -> ProjectInfo:
    pyproject_dir = Path(__file__).resolve().parent

    pyproject_data = None
    while pyproject_data is None:
        pyproject_path = Path(pyproject_dir, "pyproject.toml")
        if pyproject_path.exists() and pyproject_path.is_file():
            with open(pyproject_path, "rb") as file:
                pyproject_data = tomllib.load(file)
                break
        else:
            pyproject_dir = pyproject_dir.parent
            if len(str(pyproject_dir)) < 10:
                break

    if pyproject_data is None:
        project_info = ProjectInfo("Unknown", "Unknown", "Unknown")
    else:
        project_info_dict = pyproject_data.get("project", {})
        application_name = project_info_dict.get("name", "Unknown")
        version = project_info_dict.get("version", "Unknown")
        authors = project_info_dict.get("authors", [])
        author = authors[0].get("name", "Unknown") if authors else "Unknown"

        project_info = ProjectInfo(application_name, author, version)

    return project_info
