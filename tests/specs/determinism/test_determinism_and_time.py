import random
from datetime import datetime

from ...utils.seeds import set_seed
from ...utils.timezone import TZ, freeze_time


def test_rng_is_deterministic_with_seed():
    set_seed()
    sample_one = random.sample(range(100), 5)
    set_seed()
    sample_two = random.sample(range(100), 5)
    assert sample_one == sample_two


def test_freeze_time_uses_europe_zurich():
    with freeze_time("2025-03-30 01:30:00"):
        now = datetime.fromisoformat("2025-03-30 01:30:00")
        assert now.strftime("%Y-%m-%d %H:%M:%S") == "2025-03-30 01:30:00"
    assert TZ == "Europe/Zurich"