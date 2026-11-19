import json
from pathlib import Path

from aero_rgb.cli import HOOK_PRESETS
from aero_rgb.protocol import PRESET_ALIASES, PRESETS

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_readme_presets_table_lists_every_preset_and_alias():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table = readme.split("\n## Presets\n", 1)[1].split("\n---", 1)[0]
    for name in PRESETS:
        assert f"| `{name}`" in table, f"preset {name!r} missing from the README table"
    for alias in PRESET_ALIASES:
        assert f"`{alias}`" in table, f"alias {alias!r} missing from the README table"


def test_claude_code_hooks_example_is_valid_and_uses_known_events():
    config = json.loads((EXAMPLES / "claude-code-hooks.json").read_text(encoding="utf-8"))
    events = config["hooks"]
    assert set(events) == set(HOOK_PRESETS)
    for groups in events.values():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                assert hook["command"] == "aero-rgb hook"
    # SessionEnd hooks are cut off after 1.5 seconds unless given a longer timeout.
    assert events["SessionEnd"][0]["hooks"][0]["timeout"] >= 5
