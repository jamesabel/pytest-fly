# Spec: `active_pagefiles()`, the kernel's live page-file list, for pytest-fly

> Hand this document to Claude Code running in the **pytest-fly** repository. It is
> self-contained. The implementing agent should read `commit_memory.py` and
> `system_metrics_window.py` to confirm the current structure; the names below are
> taken from the source as of pytest-fly 0.10.5 and a working implementation of the
> reader exists in the sevenfour repository (PR #190, `src/gui/resources.py`), which
> may be copied.

## Context

`pytest_fly/pytest_runner/commit_memory.py` holds two Windows readers with one contract:

- `commit_charge_and_limit()` — the system commit charge and limit in bytes, through
  `GetPerformanceInfo` (ctypes). `None` on non-Windows platforms and on any error, the
  failure logged once, so a bad read never breaks the GUI or a run.
- `pagefile_breakdown()` — the *configured* paging files, as `PageFileInfo(path, drive,
  initial_mb, maximum_mb, system_managed)`, from the registry value
  `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles`.
  `[]` on non-Windows platforms and on any error.

The System metrics window (`gui/run_tab/system_metrics_window.py`) shows the second one
in its commit status line (`_pagefile_summary`): which discs carry a page file and their
configured sizes, plus a live total derived as commit limit minus physical RAM. It reads
the breakdown once at start and again on Reset.

## Problem

The registry holds only the **boot-time configuration**, which differs from what the
kernel is actually using in three ways:

1. **A page file activated after boot is missing.** `NtCreatePagingFile` adds and
   activates a page file at runtime with no registry entry. sevenfour's
   `setup_page_file_post_boot.py` does exactly this at every logon (a 128 GB file on
   V:, because Windows' early page-file pass skips data volumes that mount late), so on
   that machine the breakdown lists one file while two are active.
2. **System-managed entries are a wildcard with no size.** The registry records the
   system drive's managed file as `?:\pagefile.sys 0 0`; the live size and use are only
   knowable from the kernel. The summary can show the drive but not a number.
3. **There is no per-file usage at all.** `psutil.swap_memory()` gives one aggregate,
   and it is an estimate derived from commit and physical figures rather than the
   kernel's per-file "in use" count.

Net effect: the status line's per-disc list can be wrong (a file missing) and its sizes
blank, and nothing shows how much of each file is in use.

## Proposal

Add a third reader, `active_pagefiles()`, beside the two existing ones, with the same
contract, and have the System metrics window list every active page file by path with
its live size and use.

### API

```python
@dataclass(frozen=True)
class PageFileUsage:
    """One page file the kernel has active right now."""

    path: str        # Win32 path, e.g. r"C:\pagefile.sys" (NT prefix "\??\" removed)
    total_bytes: int
    in_use_bytes: int
    peak_bytes: int

    @property
    def percent(self) -> float: ...   # 100 * in_use / total, 0.0 when total is 0


def active_pagefiles() -> list[PageFileUsage]:
    """Every page file the kernel has active right now, or [] if unavailable.

    Same contract as commit_charge_and_limit / pagefile_breakdown: [] on non-Windows
    platforms and on any error, the failure logged once (callers sample about once a
    second), so a bad read never breaks the GUI or a run.
    """
```

Bytes, not GB, to match `commit_charge_and_limit()`; the GUI formats.

### Source: `NtQuerySystemInformation(SystemPageFileInformation)`

This is what `Win32_PageFileUsage` (WMI) and Task Manager read. Information class 18
returns a chain of `SYSTEM_PAGEFILE_INFORMATION` entries:

```c
typedef struct _SYSTEM_PAGEFILE_INFORMATION {
    ULONG NextEntryOffset;   // 0 on the last entry
    ULONG TotalSize;         // pages
    ULONG TotalInUse;        // pages
    ULONG PeakUsage;         // pages
    UNICODE_STRING PageFileName;   // e.g. L"\??\C:\pagefile.sys"; Length is in bytes
} SYSTEM_PAGEFILE_INFORMATION;
```

Measured cost: about 50 µs per call. No privilege, no dependency, no subprocess (the
PowerShell CIM route sevenfour used elsewhere costs about a second per call and is not
suitable for a sampler).

Implementation notes, all exercised by the reference implementation:

- Declare the structs with **fixed-width ctypes types** (`c_uint16`, `c_uint32`,
  `c_void_p` for `Buffer`), not `wintypes.ULONG`: a Windows `ULONG` is 4 bytes while
  `ctypes.c_ulong` is 8 on Linux, and fixed widths keep the parser unit-testable on
  every platform.
- Call with a 4 KB buffer; on `STATUS_INFO_LENGTH_MISMATCH` (`0xC0000004`, mask the
  return to 32 bits) double it, with a 1 MB ceiling that raises `OSError`. Any other
  non-zero status raises `OSError` with the status in hex. A zero `ReturnLength` means
  no page file at all: return `[]` without logging.
- Walk the chain by `NextEntryOffset` with `Structure.from_buffer(buffer, offset)`.
  Read each name as `ctypes.string_at(Buffer, Length).decode("utf-16-le")` and strip
  the `\??\` prefix. Sizes are in pages; `mmap.PAGESIZE` is the system page size
  (`GetSystemInfo` on Windows).
- Keep the parse of the buffer in its own function (`parse_pagefile_information(buffer,
  page_size)`) so tests can build a buffer and never touch the kernel.
- Catch `(OSError, AttributeError, ValueError)` only (ctypes/ntdll load or call failure,
  a malformed name), with a module-level one-shot warning flag like
  `_pagefile_warned_once`. Never a bare `except`.

### GUI integration (`system_metrics_window.py`)

- `_pagefile_summary` lists the **active** files: `C:\pagefile.sys 0.6/26.6 GB (2%) ·
  V:\pagefile.sys 0.1/128.0 GB (0%)`, in path order as the kernel returns them. Use is
  live, so refresh the list on every sample (the read is cheap), not only at start and
  on Reset. The `(total … GB)` suffix becomes the sum of the files' sizes, which then
  agrees with the parts; keep the commit-minus-RAM derivation only as the fallback when
  the kernel read returns `[]`.
- Keep `pagefile_breakdown()` for what it still answers, "is this file system-managed",
  shown as a suffix on the matching path when the registry has it (`C:\pagefile.sys …
  system-managed`). A `?:` registry entry matches the system drive.
- When the kernel read is unavailable (non-Windows, or it failed), fall back to today's
  behaviour exactly, so nothing regresses off Windows.

Optional, if the `SystemMonitor` sample type (`system_monitor.py`) grows a field for it:
the admission and resource guards do not need per-file data; do not change them.

## Tests (`tests/test_commit_memory.py`)

- **Parser, every platform:** build a two-entry buffer with the ctypes structs (entries
  first, UTF-16 names after them, `Buffer` set to the name's address, `NextEntryOffset`
  chaining them), and assert the list, the stripped `\??\` prefix and the page-to-byte
  conversion; a one-entry buffer; `percent` with a zero total is `0.0`.
- **Fail-open, every platform:** off Windows `[]` and no warning; on Windows, patch the
  information class to an invalid value, assert `[]` twice and exactly one warning.
- **Live, Windows only** (`skipif`): at least one file, each path is `<drive>:\…pagefile.sys`
  (case-insensitive) and `0 < in_use <= total`.
- **GUI:** the status line names each file with its use; with the reader patched to `[]`
  the line matches today's text.

## Acceptance criteria

1. `active_pagefiles()` lists a page file added after boot with `NtCreatePagingFile`,
   which `pagefile_breakdown()` does not.
2. The System metrics window's commit status line names every active page file by path
   with live size and use, and its total equals the sum of the parts.
3. Off Windows, and when the kernel read fails, behaviour and text are unchanged.
4. No new runtime dependency; the reader adds no measurable cost at the sampler's rate.
5. Existing `pagefile_breakdown()` callers and tests are untouched.

## Non-goals

- Changing the commit-charge admission or resource-guard logic (they use the aggregate
  commit figures and are correct as they are).
- Linux page-file / swap enumeration (`/proc/swaps` would be the seam; leave the
  `sys.platform` check as the single return point per platform, as in
  `commit_charge_and_limit`).
- Creating or resizing page files; that stays in sevenfour's post-boot utility.

## Consumer

sevenfour will drop its own copy of the reader (`src/gui/resources.py`,
`active_pagefiles` / `parse_pagefile_information`) and import this one once a pytest-fly
release carries it, the same way it already imports `commit_charge_and_limit` and
`pagefile_breakdown`.
