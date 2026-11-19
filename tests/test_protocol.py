import pytest

from aero_rgb import protocol as p


def test_checksum_matches_corrected_spec_example():
    # docs/PROTOCOL_SPEC.md section 4: the Cyan color packet.
    assert p.checksum([0x00, 0x14, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0x00]) == 0xEC


def test_color_packet_for_cyan():
    assert p.build_color_packet((0x00, 0xFF, 0xFF)) == bytes.fromhex("00 14 00 01 00 FF FF 00 EC")


def test_mode_packet_layout():
    packet = p.build_mode_packet(p.BREATHE, speed=8, brightness=8)
    assert packet == bytes([0x00, 0x08, 0x00, 0x02, 8, 8, 0x00, 0x00, 255 - (0x08 + 0x02 + 8 + 8)])


def test_static_mode_uses_fixed_speed_byte():
    packet = p.build_mode_packet(p.STATIC, speed=9, brightness=5)
    assert packet[3] == p.STATIC.hardware_id
    assert packet[4] == p.STATIC_SPEED_BYTE
    assert packet[5] == 5


def test_unknown_commands_are_refused():
    with pytest.raises(ValueError, match="not a known-safe command"):
        p.build_packet(0x99, 0, 0, 0, 0, 0)


def test_packet_bytes_must_fit_in_a_byte():
    with pytest.raises(ValueError):
        p.build_packet(p.CMD_SET_COLOR, 0, 1, 256, 0, 0)


@pytest.mark.parametrize("name", sorted(p.PRESETS))
def test_every_preset_builds_two_valid_packets(name):
    packets = p.build_packets(p.PRESETS[name])
    assert [pkt[1] for pkt in packets] == [p.CMD_SET_COLOR, p.CMD_SET_MODE]
    for pkt in packets:
        assert len(pkt) == p.PACKET_LENGTH
        assert pkt[0] == p.REPORT_ID
        assert pkt[8] == p.checksum(pkt)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("cyan", (0, 255, 255)),
        (" Warm White ", (0xFF, 0xE4, 0xB5)),
        ("#FF5500", (0xFF, 0x55, 0x00)),
        ("ff5500", (0xFF, 0x55, 0x00)),
        ("0xFF5500", (0xFF, 0x55, 0x00)),
        ("#f50", (0xFF, 0x55, 0x00)),
        (0x123456, (0x12, 0x34, 0x56)),
        ((1, 2, 3), (1, 2, 3)),
    ],
)
def test_parse_color(text, expected):
    assert p.parse_color(text) == expected


@pytest.mark.parametrize("bad", ["notacolor", "#12345", "#GGGGGG", 0x1000000, -1, (256, 0, 0), (1, 2)])
def test_parse_color_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        p.parse_color(bad)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Static", p.STATIC),
        ("still", p.STATIC),
        ("pulse", p.BREATHE),
        ("Rainbow", p.CYCLE),
        ("RgbPulse", p.RGB_PULSE),
        ("rgb-pulse", p.RGB_PULSE),
        ("cycle_pulse", p.CYCLE_PULSE),
    ],
)
def test_parse_pattern(text, expected):
    assert p.parse_pattern(text) is expected


def test_parse_pattern_rejects_unknown():
    with pytest.raises(ValueError, match="unknown pattern"):
        p.parse_pattern("strobe")


@pytest.mark.parametrize("kwargs", [{"brightness": 11}, {"brightness": -1}, {"speed": 0}, {"speed": 11}])
def test_lighting_state_validates_ranges(kwargs):
    with pytest.raises(ValueError):
        p.LightingState.build(**kwargs)


def test_preset_aliases():
    assert p.resolve_preset("PASS") == p.PRESETS["success"]
    assert p.resolve_preset("fail") == p.PRESETS["error"]
    with pytest.raises(ValueError, match="unknown preset"):
        p.resolve_preset("party")


def test_every_preset_has_a_description():
    assert set(p.PRESET_DESCRIPTIONS) == set(p.PRESETS)


@pytest.mark.parametrize(
    "text",
    ["00 14 00 01 00 FF FF 00 EC", "0x00,0x14,0x00,0x01,0x00,0xFF,0xFF,0x00,0xEC", "00140001 00FFFF00EC".replace(" ", "")],
)
def test_parse_packet_text(text):
    assert p.parse_packet_text(text) == bytes.fromhex("00140001 00FFFF00EC".replace(" ", ""))


def test_decode_reports_checksum_match_and_mismatch():
    good = "\n".join(p.decode_packet(bytes.fromhex("00 14 00 01 00 FF FF 00 EC")))
    assert "#00FFFF" in good and "matches the spec formula" in good

    bad = "\n".join(p.decode_packet(bytes.fromhex("00 14 00 01 00 FF FF 00 EB")))
    assert "does NOT match" in bad and "EC" in bad


def test_decode_names_the_pattern():
    text = "\n".join(p.decode_packet(p.build_mode_packet(p.CYCLE, 6, 8)))
    assert "cycle" in text
