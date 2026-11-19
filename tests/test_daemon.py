import pytest

from aero_rgb.daemon import LEVEL_STATES, Reading, choose_level, describe


def reading(cpu, battery=80.0, plugged=True):
    return Reading(cpu_percent=cpu, battery_percent=battery, plugged_in=plugged)


@pytest.mark.parametrize("cpu, level", [(5, "idle"), (39.9, "idle"), (40, "active"), (79.9, "active"), (80, "high")])
def test_cpu_thresholds_from_cold_start(cpu, level):
    assert choose_level(reading(cpu)) == level


def test_hysteresis_keeps_high_until_load_drops_clearly():
    assert choose_level(reading(77), previous="high") == "high"
    assert choose_level(reading(74), previous="high") == "active"


def test_hysteresis_keeps_active_until_load_drops_clearly():
    assert choose_level(reading(37), previous="active") == "active"
    assert choose_level(reading(34), previous="active") == "idle"


def test_rising_load_does_not_use_the_lower_threshold():
    assert choose_level(reading(77), previous="active") == "active"
    assert choose_level(reading(37), previous="idle") == "idle"


def test_low_battery_on_battery_power_wins():
    assert choose_level(reading(95, battery=15, plugged=False)) == "low-battery"


def test_low_battery_while_charging_is_not_a_warning():
    # The old daemon warned here because it treated "charging" as "on battery".
    assert choose_level(reading(10, battery=15, plugged=True)) == "idle"


def test_no_battery():
    assert choose_level(reading(10, battery=None, plugged=True)) == "idle"


@pytest.mark.parametrize("level", sorted(LEVEL_STATES))
def test_every_level_has_a_state_and_description(level):
    assert describe(level, reading(50, battery=10, plugged=False))
