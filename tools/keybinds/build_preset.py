"""Generate the pack preset from the Minecraft 26.3 Fabric registry capture."""

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRESET = "launcher/controls-preset.txt"
HUD = "hh.key.hud"
LAYOUT = {HUD: "key.keyboard.j"}
UNKNOWN = "key.keyboard.unknown"

# Exact vanilla combinations confirmed in Minecraft 26.3.
SHARED_KEYS = {
    "key.mouse.middle": {"key.pickItem", "key.spectatorHotbar"},
    "key.keyboard.f3": {"key.debug.overlay", "key.debug.modifier"},
    "key.keyboard.f4": {"key.toggleSpectatorShaderEffects", "key.debug.switchGameMode"},
    "key.keyboard.c": {"key.saveToolbarActivator", "key.debug.crash", "key.debug.copyLocation"},
    "key.keyboard.x": {"key.loadToolbarActivator", "key.debug.improvedTransparency"},
    "key.keyboard.a": {"key.left", "key.debug.reloadChunk"},
    "key.keyboard.d": {"key.right", "key.debug.clearChat"},
    "key.keyboard.g": {"key.quickActions", "key.debug.showChunkBorders"},
    "key.keyboard.l": {"key.advancements", "key.debug.profiling"},
    "key.keyboard.p": {"key.socialInteractions", "key.debug.focusPause"},
    "key.keyboard.s": {"key.back", "key.debug.dumpDynamicTextures"},
    "key.keyboard.t": {"key.chat", "key.debug.reloadResourcePacks"},
    "key.keyboard.1": {"key.hotbar.1", "key.debug.profilingChart"},
    "key.keyboard.2": {"key.hotbar.2", "key.debug.fpsCharts"},
    "key.keyboard.3": {"key.hotbar.3", "key.debug.networkCharts"},
    "key.keyboard.4": {"key.hotbar.4", "key.debug.lightmapTexture"},
}


def mappings(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"key_([\w.]+):(key\.(?:keyboard|mouse)\.[\w.]+)", line, re.ASCII)
        if not match or match.group(1) in result:
            raise ValueError(f"Invalid or duplicate key mapping: {line}")
        name, key = match.groups()
        result[name] = key
    return result


def render():
    defaults = mappings((HERE / "registered-keys.txt").read_text(encoding="utf-8"))
    if len(defaults) != 63 or defaults.get(HUD) != "key.keyboard.h":
        raise ValueError("Review the preset for the changed game key registry")
    layout = defaults | LAYOUT
    by_key = {}
    for name, key in layout.items():
        if key != UNKNOWN:
            by_key.setdefault(key, set()).add(name)
    overlaps = {key: names for key, names in by_key.items() if len(names) > 1}
    if overlaps != SHARED_KEYS:
        raise ValueError(f"Unexpected key overlaps: {overlaps}")
    lines = ["# Hide and Hunt / Minecraft 26.3", "# J cycles the Hide and Hunt HUD size."]
    lines.extend(f"key_{name}:{key}" for name, key in sorted(layout.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


if __name__ == "__main__":
    (ROOT / PRESET).write_bytes(render())
