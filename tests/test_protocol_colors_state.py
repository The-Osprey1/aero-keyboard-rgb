import pytest

from aero_rgb.colors import gradient, lerp, parse_color, to_hex
from aero_rgb.protocol import (ProtocolOptions, checksum, color_packet, decode_packet, hardware_pattern_id,
                               mode_packet, normalize_pattern, software_pattern_id, state_packets)
from aero_rgb.state import BUILTIN_PRESETS, LightState


# --- protocol ---------------------------------------------------------------

def test_checksum_matches_formula_for_cyan():
    packet = color_packet((0x00, 0xFF, 0xFF))
    # 0x14 + 0x01 + 0xFF + 0xFF = 0x213 -> (255 - 0x213) & 0xFF = 0xEC
    assert packet == bytes([0x00, 0x14, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0x00, 0xEC])
    assert checksum(packet) == packet[8]


def test_mode_packet_breathe():
    assert mode_packet("pulse", 8, 8) == bytes([0x00, 0x08, 0x00, 0x02, 0x08, 0x08, 0x00, 0x00, 0xE5])


def test_static_mode_uses_configured_speed_and_brightness_flag():
    default = mode_packet("static", 9, 5)
    assert default[3:6] == bytes([0x01, 0x02, 0x05])
    flagged = mode_packet("still", 9, 5, ProtocolOptions(static_brightness_flag=0x20))
    assert flagged[5] == 0x25
    assert checksum(flagged) == flagged[8]


def test_values_are_clamped():
    packet = mode_packet("breathe", 99, 99)
    assert packet[4] == 10 and packet[5] == 10
    assert mode_packet("breathe", 0, -3)[4:6] == bytes([1, 0])


@pytest.mark.parametrize("name,software,hardware", [
    ("static", 0, 1), ("Breathe", 1, 2), ("rainbow", 78, 3), ("RgbPulse", 84, 4), ("cycle-pulse", 92, 5),
])
def test_pattern_ids(name, software, hardware):
    assert software_pattern_id(name) == software
    assert hardware_pattern_id(name) == hardware


def test_unknown_pattern():
    with pytest.raises(ValueError, match="Unknown pattern"):
        normalize_pattern("disco")


def test_decode_packet_reports_bad_checksum():
    good = color_packet((1, 2, 3), zone=2)
    assert "zone=2" in decode_packet(good) and "checksum ok" in decode_packet(good)
    bad = good[:8] + bytes([(good[8] + 1) & 0xFF])
    assert "BAD" in decode_packet(bad)


def test_state_packets_one_color_packet_per_zone():
    packets = state_packets([(1, (1, 1, 1)), (2, (2, 2, 2))], "static", 1, 7)
    assert [p[1] for p in packets] == [0x14, 0x14, 0x08]
    assert [p[3] for p in packets[:2]] == [1, 2]


# --- colors -----------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("cyan", (0, 255, 255)), ("Warm White", (255, 228, 181)), ("#00FFCC", (0, 255, 204)),
    ("00ffcc", (0, 255, 204)), ("0x00FFCC", (0, 255, 204)), ("#0fc", (0, 255, 204)), ([1, 2, 3], (1, 2, 3)),
])
def test_parse_color(value, expected):
    assert parse_color(value) == expected


def test_parse_color_custom_names_and_chains():
    custom = {"brand": "#7B2FF7", "accent": "brand", "self": "self"}
    assert parse_color("Brand", custom) == (0x7B, 0x2F, 0xF7)
    assert parse_color("accent", custom) == (0x7B, 0x2F, 0xF7)
    with pytest.raises(ValueError):
        parse_color("self", custom)


@pytest.mark.parametrize("bad", ["notacolor", "#12345", [1, 2], [0, 0, 256]])
def test_parse_color_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        parse_color(bad)


def test_gradient_and_lerp():
    stops = [(0.0, (255, 0, 0)), (0.5, (255, 255, 0)), (1.0, (0, 255, 0))]
    assert gradient(stops, 0.0) == (255, 0, 0)
    assert gradient(stops, 0.25) == (255, 128, 0)
    assert gradient(stops, 1.0) == (0, 255, 0)
    assert gradient(stops, 7) == (0, 255, 0)
    assert lerp((0, 0, 0), (100, 200, 50), 0.5) == (50, 100, 25)
    assert to_hex((0, 255, 204)) == "#00FFCC"


# --- state ------------------------------------------------------------------

def test_light_state_normalizes_and_round_trips():
    state = LightState("Pulse", "cyan", 42, 0, ((2, "red"), (1, "blue")))
    assert state.pattern == "breathe" and state.brightness == 10 and state.speed == 1
    assert state.color == (0, 255, 255)
    assert state.zones == ((2, (255, 0, 0)),)  # zone 1 is always `color`
    assert LightState.from_dict(state.to_dict()) == state


def test_from_dict_uses_base_and_rejects_typos():
    base = BUILTIN_PRESETS["busy"]
    assert LightState.from_dict({"color": "red"}, base=base) == LightState("breathe", (255, 0, 0), 8, 8)
    with pytest.raises(ValueError, match="colour"):
        LightState.from_dict({"colour": "red"})


def test_with_zone():
    state = LightState().with_zone(3, (1, 2, 3))
    assert state.zone_colors() == ((1, (255, 255, 255)), (3, (1, 2, 3)))
    assert LightState().with_zone(1, (9, 9, 9)).color == (9, 9, 9)
