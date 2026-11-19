"""keyboard_led.ps1 also works on its own, so it keeps its own copy of the presets and colors.
These tests read the script and fail if that copy drifts from the Python one."""

import re

import pytest

from aero_rgb.backends import POWERSHELL_SCRIPT
from aero_rgb.protocol import NAMED_COLORS, PATTERNS, PRESET_ALIASES, PRESETS, LightingState, resolve_preset

SCRIPT = POWERSHELL_SCRIPT.read_text(encoding="utf-8")


def powershell_presets():
    body = SCRIPT.split("switch ($Status.ToLower()) {", 1)[1]
    presets, current = {}, None
    for raw in body.splitlines():
        line = raw.strip()
        header = re.match(r'^\{\s*\$_\s+-in\s+(.+?)\s*\}\s*\{$', line) or re.match(r'^("\w+")\s*\{$', line)
        if header:
            current = {}
            for name in re.findall(r'"(\w+)"', header.group(1)):
                presets[name] = current
        elif line == "}":
            if current is None:
                break  # end of the switch block
            current = None
        elif current is not None:
            assignment = re.match(r'^\$(\w+)\s*=\s*"?([^"]+?)"?$', line)
            assert assignment, f"unexpected line in preset block: {line!r}"
            current[assignment.group(1)] = assignment.group(2)
    return presets


PS_PRESETS = powershell_presets()


def test_status_parameter_accepts_every_python_preset():
    validate_set = re.search(r'\[ValidateSet\(([^)]*)\)\]\s*\[string\]\$Status', SCRIPT).group(1)
    names = set(re.findall(r'"(\w+)"', validate_set))
    assert names == set(PRESETS) | set(PRESET_ALIASES)
    assert set(PS_PRESETS) == names


@pytest.mark.parametrize("name", sorted(set(PRESETS) | set(PRESET_ALIASES)))
def test_preset_matches(name):
    values = PS_PRESETS[name]
    # Unset values fall back to the script's parameter defaults.
    from_script = LightingState.build(
        pattern=values.get("Pattern", "Static"),
        color=values.get("Color", "White"),
        brightness=int(values.get("Brightness", 7)),
        speed=int(values.get("Speed", 8)),
    )
    assert from_script == resolve_preset(name)


def test_color_table_matches():
    block = SCRIPT.split("$ColorMap = @{", 1)[1].split("}", 1)[0]
    colors = {name: int(value, 16) for name, value in re.findall(r'"(\w+)"\s*=\s*0x([0-9A-Fa-f]{6})', block)}
    assert colors == NAMED_COLORS


def test_pattern_ids_match():
    block = SCRIPT.split("switch ($Pattern.ToLower()) {", 1)[1].split("\n}", 1)[0]
    ids = {name: int(value) for name, value in re.findall(r'"(\w+)"\s*\{\s*\$pattId\s*=\s*(\d+)\s*\}', block)}
    for pattern in PATTERNS.values():
        assert ids[pattern.powershell_name.lower()] == pattern.control_center_id
    assert ids["pulse"] == ids["breathe"] and ids["rainbow"] == ids["cycle"]
