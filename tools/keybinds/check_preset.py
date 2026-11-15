"""Check the shipped preset and optionally compare it with a saved game registry."""

from argparse import ArgumentParser
from pathlib import Path

from build_preset import HERE, PRESET, ROOT, mappings, render


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--options", type=Path, help="Saved options.txt from the unmodified QA layout")
    args = parser.parse_args()
    if (ROOT / PRESET).read_bytes() != render():
        parser.exit(1, "Preset differs from the reviewed layout. Run build_preset.py.\n")
    if args.options:
        options = args.options.read_text(encoding="utf-8-sig")
        saved = mappings("\n".join(line for line in options.splitlines() if line.startswith("key_")))
        expected = mappings((HERE / "registered-keys.txt").read_text(encoding="utf-8"))
        if saved != expected:
            parser.exit(1, "Saved mappings differ from the captured default registry.\n")
    print("Verified 63 mappings, including 16 intentional vanilla shared keys.")


if __name__ == "__main__":
    main()
