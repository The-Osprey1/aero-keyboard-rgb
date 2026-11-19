"""Things that live in more than one place must agree.

keyboard_led.ps1 also works on its own, so it keeps its own copy of the presets, colors and
pattern numbers. The README lists the presets, and examples/ holds Claude Code settings.
"""

import json
import re
from pathlib import Path

import pytest

from aero_rgb import hooks
from aero_rgb.backends import POWERSHELL_SCRIPT
from aero_rgb.colors import NAMED_COLORS, parse_color
from aero_rgb.protocol import normalize_pattern, software_pattern_id
from aero_rgb.state import BUILTIN_PRESETS, PRESET_ALIASES

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = POWERSHELL_SCRIPT.read_text(encoding="utf-8")
ALL_PRESET_NAMES = set(BUILTIN_PRESETS) | set(PRESET_ALIASES)


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
            assert assignment, f"unexpected line in a preset block: {line!r}"
            current[assignment.group(1)] = assignment.group(2)
    return presets


PS_PRESETS = powershell_presets()


def test_powershell_status_parameter_accepts_every_preset():
    validate_set = re.search(r'\[ValidateSet\(([^)]*)\)\]\s*\[string\]\$Status', SCRIPT).group(1)
    assert set(re.findall(r'"(\w+)"', validate_set)) == ALL_PRESET_NAMES
    assert set(PS_PRESETS) == ALL_PRESET_NAMES


@pytest.mark.parametrize("name", sorted(ALL_PRESET_NAMES))
def test_powershell_preset_matches_python(name):
    values = PS_PRESETS[name]
    expected = BUILTIN_PRESETS[PRESET_ALIASES.get(name, name)]
    # Settings the script's preset doesn't set fall back to its parameter defaults.
    assert normalize_pattern(values.get("Pattern", "Static")) == expected.pattern
    assert parse_color(values.get("Color", "White")) == expected.color
    assert int(values.get("Brightness", 7)) == expected.brightness
    if expected.pattern != "static":  # static ignores speed
        assert int(values.get("Speed", 8)) == expected.speed


def test_powershell_colors_match_python():
    block = SCRIPT.split("$ColorMap = @{", 1)[1].split("}", 1)[0]
    colors = {name: int(value, 16) for name, value in re.findall(r'"(\w+)"\s*=\s*0x([0-9A-Fa-f]{6})', block)}
    assert colors, "could not read the script's color table"
    for name, value in colors.items():
        assert parse_color(f"#{value:06X}") == NAMED_COLORS[name], name


def test_powershell_pattern_numbers_match_python():
    block = SCRIPT.split("switch ($Pattern.ToLower()) {", 1)[1].split("\n}", 1)[0]
    ids = dict(re.findall(r'"(\w+)"\s*\{\s*\$pattId\s*=\s*(\d+)\s*\}', block))
    assert ids, "could not read the script's pattern table"
    for name, value in ids.items():
        assert software_pattern_id(name) == int(value), name


def test_readme_presets_table_lists_every_preset():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table = readme.split("Built-in presets:", 1)[1].split("\n## ", 1)[0]
    for name in sorted(ALL_PRESET_NAMES):
        assert f"`{name}`" in table, f"{name!r} is missing from the README presets table"


def test_claude_code_example_settings():
    config = json.loads((ROOT / "examples" / "claude-code-hooks.json").read_text(encoding="utf-8"))
    events = config["hooks"]
    assert set(events) == set(hooks.HANDLED_EVENTS)
    for event, groups in events.items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook == {**hook, "type": "command", "command": "aero-rgb hook"}
                if event == "SessionEnd":
                    # Claude Code cancels SessionEnd hooks after 1.5 seconds unless given more time,
                    # and a background (async) hook may be cut off when the session closes.
                    assert hook.get("timeout", 0) >= 5 and not hook.get("async")
                else:
                    assert hook.get("async") is True  # never delay Claude
