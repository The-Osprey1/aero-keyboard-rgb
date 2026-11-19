import pytest

from aero_rgb.cli import main
from aero_rgb.protocol import parse_packet_text

CYAN = bytes.fromhex("00 14 00 01 00 FF FF 00 EC")


@pytest.mark.parametrize("text", [
    "00 14 00 01 00 FF FF 00 EC",
    "0x00,0x14,0x00,0x01,0x00,0xFF,0xFF,0x00,0xEC",
    "00:14:00:01:00:ff:ff:00:ec",
    "[00, 14, 00, 01, 00, FF, FF, 00, EC]",
    "00140001 00FFFF00EC".replace(" ", ""),
])
def test_parse_packet_text(text):
    assert parse_packet_text(text) == CYAN


@pytest.mark.parametrize("text", ["zz", "0014000", "", "100"])
def test_parse_packet_text_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_packet_text(text)


def test_decode_command_checks_the_checksum(capsys):
    assert main(["decode", "00", "14", "00", "01", "00", "FF", "FF", "00", "EC"]) == 0
    out = capsys.readouterr().out
    assert "rgb=#00FFFF" in out and "checksum ok" in out

    # The original spec's worked example: one off.
    assert main(["decode", "00 14 00 01 00 FF FF 00 EB"]) == 0
    assert "BAD (expected EC)" in capsys.readouterr().out


def test_decode_command_reports_bad_input(capsys):
    assert main(["decode", "nonsense"]) == 1
    assert "Could not read bytes" in capsys.readouterr().err
