import time

import pytest


@pytest.mark.singleton
def test_singleton_b():
    time.sleep(2)
    assert True
