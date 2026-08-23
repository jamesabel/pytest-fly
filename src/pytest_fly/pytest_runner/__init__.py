"""pytest-fly test runner package.

The runner classes are resolved lazily (PEP 562): spawn children unpickle
:class:`ProcessMonitor` / :class:`PytestProcess` / :class:`GetTests` through this package, and
an eager ``from .pytest_runner import PytestRunner`` here would drag the whole orchestration
layer (and, transitively, pytest) into every child.
"""

from typing import Any

__all__ = ["GetTests", "PytestRunState", "PytestRunner"]

_LAZY = {
    "PytestRunner": ("pytest_fly.pytest_runner.pytest_runner", "PytestRunner"),
    "PytestRunState": ("pytest_fly.pytest_runner.pytest_runner", "PytestRunState"),
    "GetTests": ("pytest_fly.pytest_runner.test_list", "GetTests"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    from importlib import import_module

    return getattr(import_module(module_name), attribute)
