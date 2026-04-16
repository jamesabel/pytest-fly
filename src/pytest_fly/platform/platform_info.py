"""
Platform and hardware introspection — CPU core classification, memory, and
system metadata.

On Windows, uses ``GetLogicalProcessorInformationEx`` to distinguish
performance (P) and efficiency (E) cores on hybrid CPUs.
"""

import getpass
import platform
import struct
import sys
from functools import cache

import psutil
from cpuinfo import get_cpu_info


@cache
def get_user_name():
    return getpass.getuser()


@cache
def get_computer_name():
    return platform.node()


def _get_p_core_count_windows() -> int | None:
    """
    Use GetLogicalProcessorInformationEx to count physical P-cores on Windows.

    Each RelationProcessorCore record in the API response contains an EfficiencyClass byte:
        0  = E-core (efficiency / low-power core)
        >0 = P-core (performance core)

    On non-hybrid CPUs every core reports EfficiencyClass = 0; in that case all
    cores are treated as P-cores and the total physical core count is returned.

    Returns None if not on Windows or if the API call fails for any reason.
    """
    if sys.platform != "win32":
        return None

    import ctypes

    RelationProcessorCore = 0
    kernel32 = ctypes.windll.kernel32

    # First call with a null buffer to discover the required buffer size.
    size = ctypes.c_ulong(0)
    kernel32.GetLogicalProcessorInformationEx(RelationProcessorCore, None, ctypes.byref(size))
    if size.value == 0:
        return None

    buf = (ctypes.c_ubyte * size.value)()
    if not kernel32.GetLogicalProcessorInformationEx(RelationProcessorCore, ctypes.byref(buf), ctypes.byref(size)):
        return None

    # Parse the variable-length SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX records.
    # Each record layout (relevant offsets):
    #   +0  Relationship  DWORD  (always RelationProcessorCore = 0 here)
    #   +4  Size          DWORD  (total byte length of this record)
    #   +8  Flags         BYTE   (PROCESSOR_RELATIONSHIP)
    #   +9  EfficiencyClass BYTE (0 = E-core, 1 = P-core on current Intel/AMD hybrid)
    p_cores = 0
    e_cores = 0
    offset = 0
    while offset < size.value:
        record_size = struct.unpack_from("<I", buf, offset + 4)[0]
        if record_size == 0:
            break  # guard against a malformed record causing an infinite loop
        efficiency_class = struct.unpack_from("B", buf, offset + 9)[0]
        if efficiency_class > 0:
            p_cores += 1
        else:
            e_cores += 1
        offset += record_size

    # On non-hybrid CPUs all cores report EfficiencyClass = 0.
    # In that case there is no distinction, so return the total core count.
    if p_cores == 0:
        return e_cores
    return p_cores


@cache
def get_performance_core_count() -> int:
    """
    Return the number of performance (P) cores available on the system.

    On Windows, reads the EfficiencyClass field from GetLogicalProcessorInformationEx
    for an authoritative per-core classification.

    On other platforms, falls back to a heuristic that relies on Intel hybrid CPUs
    giving Hyper-Threading to P-cores but not to E-cores:
        p_core_count = logical_thread_count - physical_core_count

    This value is typically used to decide the default degree of test parallelism.
    """
    count = _get_p_core_count_windows()
    if count is not None:
        return count

    # Heuristic fallback for non-Windows (or if the Windows API call failed).
    all_core_count = psutil.cpu_count(False)  # physical cores (P + E)
    thread_count = psutil.cpu_count()  # logical threads (includes HT)
    if all_core_count == thread_count:
        # No HT at all; cannot distinguish P from E cores — return total.
        return all_core_count
    # Intel hybrid: p_cores have HT (2 threads each), e_cores do not (1 thread each).
    # thread_count = p*2 + e,  all_core_count = p + e  →  p = thread_count - all_core_count
    return thread_count - all_core_count


@cache
def get_efficiency_core_count() -> int:
    """
    Return the number of efficiency (E) cores on the system, or 0 on non-hybrid CPUs.
    """
    all_core_count = psutil.cpu_count(False)
    return all_core_count - get_performance_core_count()


@cache
def get_platform_info(details: bool = False) -> dict:
    cpu_freq = psutil.cpu_freq()
    virtual_memory = psutil.virtual_memory()

    platform_info = {
        "computer_name": get_computer_name(),
        "user_name": get_user_name(),
        "memory_total": virtual_memory.total,
        "cpu_count_logical": psutil.cpu_count(),  # includes hyperthreading
        "cpu_count_all_cores": psutil.cpu_count(False),  # includes efficiency cores
        "cpu_count_performance_cores": get_performance_core_count(),  # only performance cores if mix of performance and efficiency cores
        "cpu_count_efficiency_cores": get_efficiency_core_count(),
        "platform_string": platform.platform(),
        "processor": platform.processor(),
        "cpu_freq_min": cpu_freq.min,
        "cpu_freq_max": cpu_freq.max,
    }

    cpu_info = get_cpu_info()
    keys = [
        "hz_actual_friendly",
        "python_version",
        "vendor_id_raw",
        "hardware_raw",
        "brand_raw",
        "arch_string_raw",
        "l1_data_cache_size",
        "l1_instruction_cache_size",
        "l2_cache_size",
        "l3_cache_size",
        "processor_type",
    ]

    if details:
        # platform information some users may not care about
        keys.append("l2_cache_line_size")
        keys.append("l2_cache_associativity")
        keys.append("stepping")
        keys.append("model")
        keys.append("family")

    for key in keys:
        value = cpu_info.get(key)
        if value is not None:
            if isinstance(value, str):
                value = value.strip()
            if isinstance(value, int) or (isinstance(value, str) and len(value) > 0):
                if key.endswith("_raw"):
                    field = key[:-4]
                else:
                    field = key
                platform_info[field] = value

    return platform_info
