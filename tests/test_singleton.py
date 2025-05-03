import time

import pytest


@pytest.mark.singleton
def test_singleton():
    a = 1
    time.sleep(0.01)
    assert a == 1
