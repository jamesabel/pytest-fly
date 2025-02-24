from functools import cache
import platform
import getpass

import psutil
from cpuinfo import get_cpu_info

@cache
def get_user_name():
    return getpass.getuser()

@cache
def get_computer_name():
    return platform.node()

@cache
def get_performance_core_count() -> int:
    """
    Get the number of cores on the system. If there are a mix of performance and efficiency cores, return only the number of performance cores (HT must be enabled).
    This is usually used when trying to decide how many processes to run in parallel.
    Use this instead of psutil.cpu_count(False) directly.
    :return: number of cores
    """
    all_core_count = psutil.cpu_count(False)  # real cores, but both performance and efficiency cores
    thread_count = psutil.cpu_count()  # includes hyperthreading
    if all_core_count % thread_count == 0:
        # no mix of performance and efficiency cores (historical method)
        core_count = all_core_count
    else:
        # workaround for mix of performance and efficiency cores
        # requires hyperthreading to be enabled for performance cores (efficiency cores don't have HT)
        core_count = thread_count - all_core_count

    return core_count

def get_efficiency_core_count() -> int:
    """
    Get the number of efficiency cores on the system. If there are a mix of performance and efficiency cores, return only the number of efficiency cores (HT must be enabled).
    This is usually used when trying to decide how many processes to run in parallel.
    Use this instead of psutil.cpu_count(False) directly.
    :return: number of cores
    """
    all_core_count = psutil.cpu_count(False)  # real cores, but both performance and efficiency cores
    performance_core_count = get_performance_core_count()
    efficiency_core_count = all_core_count - performance_core_count

    return efficiency_core_count

@cache
def get_platform_info(details: bool = False) -> dict:
    cpu_freq = psutil.cpu_freq()
    virtual_memory = psutil.virtual_memory()

    platform_info = {
        "cpu_count_logical": psutil.cpu_count(),  # includes hyperthreading
        "cpu_count_all_cores": psutil.cpu_count(False),  # includes efficiency cores
        "cpu_count_performance_cores": get_performance_core_count(),  # only performance cores if mix of performance and efficiency cores
        "cpu_count_efficiency_cores": get_efficiency_core_count(),
        "cpu_freq_min": cpu_freq.min,
        "cpu_freq_max": cpu_freq.max,
        "memory_total": virtual_memory.total,
        "computer_name": get_computer_name(),
        "user_name": get_user_name(),
        "platform_string": platform.platform(),
        "processor": platform.processor(),
    }

    cpu_info = get_cpu_info()
    keys = [
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
