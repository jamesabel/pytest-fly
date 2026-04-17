import time

import pytest


@pytest.mark.singleton
def test_singleton_a():
    time.sleep(2)
    assert True
