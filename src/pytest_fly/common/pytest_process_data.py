# import weakref
# from multiprocessing import Manager
# from typing import Iterator
# from dataclasses import dataclass
#
# @dataclass(frozen=True)
# class PytestProcessData:
#     pid: int
#     name: str
#
#
# class SharedPytestProcessData:
#     """
#     A shared list of PytestProcessData that can be accessed by multiple processes.
#     """
#
#     def __init__(self) -> None:
#         self._manager = Manager()
#         self._list = self._manager.list()
#
#         # Automatically shut down the Manager when this object is garbage-collected.
#         self._finalizer = weakref.finalize(self, self._manager.shutdown)
#
#     def __contains__(self, pytest_process_data: PytestProcessData) -> bool:
#         """
#         Allows "in" checks, e.g. `if "some_string" in shared_list`.
#         """
#         return pytest_process_data in self._list
#
#     def append(self, pytest_process_data: PytestProcessData) -> None:
#         """
#         Append a string to the shared list.
#         """
#         self._list.append(pytest_process_data)
#
#     def remove(self, pytest_process_data: PytestProcessData) -> None:
#         """
#         Remove a string from the shared list.
#         """
#         self._list.remove(pytest_process_data)
#
#     def __getitem__(self, index: int) -> str:
#         """
#         Allow bracket access, e.g. shared_list[0].
#         """
#         return self._list[index]
#
#     def __setitem__(self, index: int, pytest_process_data: PytestProcessData) -> None:
#         """
#         Allow bracket assignment, e.g. shared_list[0] = "new_value".
#         """
#         self._list[index] = pytest_process_data
#
#     def __iter__(self) -> Iterator[PytestProcessData]:
#         """
#         Iterate over the strings in the shared list.
#         """
#         return iter(self._list)
#
#     def __len__(self) -> int:
#         """
#         Return the number of strings in the shared list.
#         """
#         return len(self._list)
#
#     def to_list(self) -> list[PytestProcessData]:
#         """
#         Return a snapshot of the shared list as a regular Python list of strings.
#         """
#         return list(self._list)
