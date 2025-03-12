import time
import random


def test_do_something():
    """
    This function does something that consumes 1 CPU and some memory.
    """

    duration = 3.0  # seconds

    data = []
    inside_circle = 0
    start = time.time()
    num_points = 0
    while True:
        # consume memory
        data.append(" " * int(1e6))

        # calculate pi using monte carlo simulation
        x, y = random.random(), random.random()
        if x**2 + y**2 <= 0.25:
            inside_circle += 1
        num_points += 1
        if time.time() - start > duration:
            break

    pi = (inside_circle / num_points) * 16
    print(f"{pi=}")
