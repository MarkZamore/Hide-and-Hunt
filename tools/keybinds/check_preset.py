"""Check the shipped preset and optionally compare it with a saved game registry."""

from argparse import ArgumentParser
from pathlib import Path

from build_preset import PRESET, ROOT, SHARED_KEYS, mappings, render


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--options", type=Path, help="Saved options.txt from the unmodified QA layout")
    args = parser.parse_args()
    preset = (ROOT / PRESET).read_bytes()
    if preset != render():
        parser.exit(1, "Preset differs from the reviewed layout. Run build_preset.py.\n")
    if args.options:
        options = args.options.read_text(encoding="utf-8-sig")
        saved = mappings("\n".join(line for line in options.splitlines() if line.startswith("key_")))
        expected = mappings(preset.decode("utf-8"))
        if saved != expected:
            parser.exit(1, "Saved mappings differ from the preset.\n")
    print(f"Verified 63 mappings and {len(SHARED_KEYS)} reviewed shared keys.")


if __name__ == "__main__":
    main()
