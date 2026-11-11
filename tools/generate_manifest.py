"""Record a reviewed Hide and Hunt distribution and stage or verify its assets."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import network_logging_policy
from pack_library import build_library, read_mods
from prepare_26_3 import OUTPUT_NAME, build as prepare_26_3
from public_server_policy import POLICY, inventory_sha256, verify as verify_server_policy


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = "portable-pack.json"
BRIDGE = "mods/lanminecraft-hide-and-hunt-bridge-1.0.0.jar"
BRIDGE_ID = "lanminecraft_hide_and_hunt_bridge"
UPSTREAM_LOCK = "tools/upstream-lock.json"
OVERLAY = "tools/overlay.json"
INVENTORY = "library/loaded-mods.json"
DISTRIBUTION_LOCK = "tools/distribution-lock.json"
SERVER_POLICY = "tools/public-server-policy.json"
CAPABILITY = "steam-native-publication-metadata-v1"
PLATFORM = {"schemaVersion": 1, "minecraftVersion": "26.3", "loader": {"type": "fabric", "version": "0.20.1"},
            "javaMajorVersion": 25}
NOTICE_FILES = (
    "Directories-MPL-2.0.txt", "e4mc-MIT.txt", "Fabric-API-Apache-2.0.txt", "GPL-3.0.txt",
    "HideAndHunt-MIT.txt", "Kaleido-Config-LGPL-3.0.txt", "Netty-QUIC-NOTICE.txt",
    "Night-Config-LGPL-3.0.txt", "Quilt-Config-Apache-2.0.txt", "THIRD-PARTY.txt",
)
AUTHORED_FILES = {
    DESCRIPTOR: DESCRIPTOR,
    "config/log4j2.xml": "config/log4j2.xml",
    "launcher/jvm-args.txt": "launcher/jvm-args.txt",
    "launcher/pack-owned.txt": "launcher/pack-owned.txt",
    "launcher/notices/LANMinecraft-MIT.txt": "LICENSE",
    **{"launcher/notices/" + name: "notices/" + name for name in NOTICE_FILES},
}
PACK_IDS = {"hideandhunt_bundle", "hideandhunt", "e4mc", "fabric-api", BRIDGE_ID}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_file(path):
    require(path.is_file() and not path.is_symlink() and not path.is_junction(), f"Invalid input file: {path}")
    return path.read_bytes()


def unique_object(rows):
    obj = {}
    for key, value in rows:
        require(key not in obj, f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def parse_json(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def digest(raw):
    return sha256(raw).hexdigest()


def fingerprint(raw):
    return {"sizeBytes": len(raw), "sha256": digest(raw)}


def check_pin(raw, pin, name):
    require(all(pin.get(key) == value for key, value in fingerprint(raw).items()), f"Size/SHA256 mismatch: {name}")


def nested_file(raw, entries):
    for entry in entries:
        with ZipFile(BytesIO(raw)) as archive:
            matches = [member for member in archive.infolist() if member.filename == entry]
            require(len(matches) == 1 and not matches[0].is_dir(), f"Invalid locked JAR entry: {entry}")
            raw = archive.read(matches[0])
    return raw


def source_inputs(upstream, bridge):
    lock = parse_json(read_file(ROOT / UPSTREAM_LOCK))
    require(lock.get("schemaVersion") == 1 and lock.get("release") == "FaWrAGlY", "Unexpected author input lock")
    input_path = lock["file"]["path"]
    require(re.fullmatch(r"mods/[A-Za-z0-9.+-]+\.jar", input_path) is not None, "Invalid upstream JAR path")
    check_pin(upstream, lock["file"], input_path)
    for row in lock["selected"]:
        raw = nested_file(upstream, row["entries"])
        check_pin(raw, row, row["id"])
        with ZipFile(BytesIO(raw)) as archive:
            metadata = parse_json(archive.read("fabric.mod.json"))
        require((metadata.get("id"), metadata.get("version")) == (row["id"], row["version"]),
                f"Locked nested Fabric metadata changed: {row['id']}")
        if "license" in metadata:
            require(metadata["license"] == row["license"], f"Locked nested license changed: {row['id']}")

    with ZipFile(BytesIO(bridge)) as archive:
        metadata = parse_json(archive.read("fabric.mod.json"))
    require((metadata.get("id"), metadata.get("version")) == (BRIDGE_ID, "1.0.0"),
            "Expected the 1.0.0 pack-owned Hide and Hunt bridge")
    return {"mods/" + OUTPUT_NAME: prepare_26_3(upstream), BRIDGE: bridge}


def all_payload(jars):
    network_logging_policy.verify(ROOT)
    payload = {path: read_file(ROOT / source) for path, source in AUTHORED_FILES.items()}
    require(parse_json(payload[DESCRIPTOR]) == PLATFORM, "Unexpected pack runtime descriptor")
    return dict(sorted((payload | jars).items()))


def native_candidates(jars):
    candidates = {}
    for path, raw in jars.items():
        for mod in read_mods(raw, Path(path).name, loader="fabric"):
            if mod["isLoadedMod"]:
                candidates.setdefault((mod["id"], mod["version"]), (mod["name"], path))
    return candidates


def verify_observed_infrastructure(observations):
    require(observations.get("minecraft") == PLATFORM["minecraftVersion"]
            and observations.get("fabricloader") == PLATFORM["loader"]["version"]
            and str(observations.get("java", "")).split(".")[0] == str(PLATFORM["javaMajorVersion"])
            and observations.get("e4steam") == "0.3.4+modern",
            "Native observations must include the pinned Minecraft, Fabric, Java and shared e4steam")
    excluded = {"minecraft", "fabricloader", "java", "e4steam"}
    require(observations.get("mixinextras") == "0.5.5", "Unexpected Fabric Loader bundled MixinExtras version")
    excluded.add("mixinextras")
    return excluded


def record_inventory(jars, raw_observations):
    observations = parse_json(raw_observations)
    require(isinstance(observations, dict) and all(isinstance(item, str) and item.strip()
            for item in observations.values()), "Expected a native Fabric mod ID to version JSON object")
    excluded = verify_observed_infrastructure(observations)
    candidates = native_candidates(jars)
    observed_pack = set(observations) - excluded
    require(PACK_IDS <= observed_pack, "Native inventory omits a required pack mod")
    rows = []
    for mod_id in sorted(observed_pack):
        version = observations[mod_id]
        require((mod_id, version) in candidates, f"Unexpected native mod/version: {mod_id} {version}")
        name, source = candidates[mod_id, version]
        rows.append({"id": mod_id, "name": name, "version": version, "source": source})
    return {
        "schemaVersion": 1,
        "minecraftVersion": PLATFORM["minecraftVersion"],
        "loader": PLATFORM["loader"],
        "observationSha256": digest(raw_observations),
        "sourceJars": {path: digest(raw) for path, raw in jars.items()},
        "managedInfrastructure": {mod_id: observations[mod_id] for mod_id in sorted(excluded)},
        "mods": rows,
    }


def load_inventory(jars):
    raw = read_file(ROOT / INVENTORY)
    inventory = parse_json(raw)
    require(inventory.get("schemaVersion") == 1 and inventory.get("minecraftVersion") == PLATFORM["minecraftVersion"]
            and inventory.get("loader") == PLATFORM["loader"] and
            inventory.get("sourceJars") == {path: digest(data) for path, data in jars.items()} and
            re.fullmatch(r"[a-f0-9]{64}", inventory.get("observationSha256", "")) is not None,
            "Native inventory is stale or incomplete")
    infrastructure = inventory.get("managedInfrastructure")
    require(isinstance(infrastructure, dict) and set(infrastructure) == verify_observed_infrastructure(infrastructure),
            "Native inventory has unknown managed infrastructure IDs")
    candidates = native_candidates(jars)
    seen = set()
    for row in inventory["mods"]:
        mod_id = row["id"]
        require(mod_id not in seen and candidates.get((mod_id, row["version"])) == (row["name"], row["source"]),
                f"Unexpected native mod ID, version or source: {mod_id}")
        seen.add(mod_id)
    require(PACK_IDS <= seen, "Native inventory omits a required pack mod")
    return raw, inventory


def source_fingerprint(root):
    sources = [root / "build.py", root / "inputs.json"]
    for folder in ("src", "resources", "verify"):
        sources.extend(path for path in (root / folder).rglob("*") if path.is_file())
    return digest(json_bytes({
        path.relative_to(root).as_posix(): digest(read_file(path))
        for path in sorted(sources)
    }))


def distribution_receipt(payload, inventory_raw):
    files = [{"path": path, **fingerprint(raw)} for path, raw in payload.items()]
    return {
        "schemaVersion": 1,
        "upstreamLockSha256": digest(read_file(ROOT / UPSTREAM_LOCK)),
        "overlayRecipeSha256": digest(read_file(ROOT / OVERLAY)),
        "compatibilitySources": {
            path: digest(read_file(ROOT / path))
            for path in ("tools/prepare_26_3.py", "tools/prepare_e4mc_compat.py")
        },
        "bridgeSourcesSha256": source_fingerprint(ROOT / "bridge"),
        "nativeInventorySha256": digest(inventory_raw),
        "files": files,
    }


def server_policy(files):
    return {"schemaVersion": 1, "policy": POLICY, "reviewedInventorySha256": inventory_sha256(files)}


def release_inputs(jars):
    inventory_raw, inventory = load_inventory(jars)
    payload = all_payload(jars)
    receipt = distribution_receipt(payload, inventory_raw)
    require(parse_json(read_file(ROOT / DISTRIBUTION_LOCK)) == receipt,
            "Distribution lock does not match the reviewed source, bridge or native inventory")
    require(parse_json(read_file(ROOT / SERVER_POLICY)) == server_policy(receipt["files"]),
            "Steam-only automatic server-list review is missing or stale")
    return payload, inventory, receipt["files"]


def zip_root(entries):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_STORED) as archive:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            archive.writestr(info, data)
    return buffer.getvalue()


def library_bundle(payload, files, revision, work_root):
    with TemporaryDirectory(prefix=".library-inputs-", dir=work_root) as temp:
        pack = Path(temp)
        for path, raw in payload.items():
            target = pack / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        verify_server_policy(pack, {"files": files}, policy=ROOT / SERVER_POLICY)
        (pack / "library").mkdir()
        for path in (INVENTORY, "library/content.json", "library/mod-pages.json", "library/preview.jpg"):
            (pack / path).write_bytes(read_file(ROOT / path))
        preview = read_file(pack / "library/preview.jpg")
        require(4 <= len(preview) <= 8 * 1024 * 1024 and preview.startswith(b"\xff\xd8") and preview.endswith(b"\xff\xd9"),
                "Expected a JPEG preview within the launcher bundle limit")
        # Use the shared metadata generator, then freeze ZIP storage as well as
        # timestamps so different platform zlib releases cannot change the SHA.
        with ZipFile(BytesIO(build_library(pack, revision))) as generated:
            bundle = zip_root({name: generated.read(name) for name in ("library.json", "preview.jpg")})
        require(len(bundle) <= 8 * 1024 * 1024, "Library bundle exceeds the launcher limit")
        return bundle


def release_bytes(jars, revision, work_root):
    payload, inventory, files = release_inputs(jars)
    contents = {}
    assets = []

    def add_asset(label, extension, kind, raw, covers):
        name = f"{label}-{digest(raw)}.{extension}"
        require(name not in contents, f"Duplicate immutable asset: {name}")
        contents[name] = raw
        assets.append({"name": name, "kind": kind, **fingerprint(raw), "covers": covers})

    for path, raw in jars.items():
        add_asset("mod", "jar", "jar", raw, [path])
    add_asset("descriptor", "json", "jar", payload[DESCRIPTOR], [DESCRIPTOR])
    for directory in ("config", "launcher"):
        entries = {path: raw for path, raw in payload.items() if path.startswith(directory + "/")}
        add_asset(directory, "zip", "zipRoot", zip_root(entries), list(entries))

    raw_library = library_bundle(payload, files, revision, work_root)
    library_name = "library-" + digest(raw_library) + ".zip"
    contents[library_name] = raw_library
    manifest = {
        "schemaVersion": 2, "packId": "minecraft-11", "revision": revision,
        "minecraftVersion": PLATFORM["minecraftVersion"], "loader": PLATFORM["loader"],
        "modCount": len(inventory["mods"]), "requiredLauncherFeatures": [CAPABILITY],
        "files": files, "assets": sorted(assets, key=lambda asset: asset["name"]),
        "library": {"name": library_name, "revision": revision, **fingerprint(raw_library)},
    }
    require(parse_json(read_file(ROOT / "library/content.json"))["id"] == manifest["packId"],
            "Pack manifest and library IDs differ")
    return json_bytes(manifest), contents


def validate_revision(value):
    require(re.fullmatch(r"[a-f0-9]{40}", value) is not None, "Expected a full lowercase Git revision")
    return value


def git_revision():
    git = ["git", "-C", str(ROOT)]
    revision = validate_revision(subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip())
    dirty = subprocess.check_output([*git, "status", "--porcelain", "--untracked-files=all"], text=True)
    require(not dirty, "A release must be staged or verified from a clean Git checkout")
    return revision


def stage(out, revision, jars):
    require(not out.exists() and not out.is_symlink(), "Stage output must be a new directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest, assets = release_bytes(jars, revision, out.parent)
    out.mkdir()
    asset_dir = out / "assets"
    created = []
    try:
        asset_dir.mkdir()
        for name, raw in sorted(assets.items()):
            target = asset_dir / name
            created.append(target)
            target.write_bytes(raw)
        target = out / "pack-manifest.json"
        created.append(target)
        target.write_bytes(manifest)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        if asset_dir.exists():
            asset_dir.rmdir()
        out.rmdir()
        raise
    return len(assets)


def verify(out, revision, upstream):
    lock = parse_json(read_file(ROOT / DISTRIBUTION_LOCK))
    jar_names = {item["path"]: "mod-" + item["sha256"] + ".jar"
                 for item in lock["files"] if item["path"].startswith("mods/")}
    # Derive names from the reviewed lock, never from the downloaded manifest.
    require(all(re.fullmatch(r"mod-[a-f0-9]{64}\.jar", name) for name in jar_names.values()),
            "Invalid reviewed JAR hash")
    asset_dir = out / "assets"
    jars = source_inputs(upstream, read_file(asset_dir / jar_names[BRIDGE]))
    expected_manifest, expected_assets = release_bytes(jars, revision, out.parent)
    require(read_file(out / "pack-manifest.json") == expected_manifest,
            "Manifest bytes do not match the reviewed Git revision")
    require({entry.name for entry in asset_dir.iterdir()} == set(expected_assets),
            "Release asset directory has missing or unexpected entries")
    for name, expected in expected_assets.items():
        require(read_file(asset_dir / name) == expected, f"Asset bytes do not match the reviewed release: {name}")
    return len(expected_assets)


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments[:1] == ["--verify-only"]:
        arguments[0] = "verify"
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "review", "record-lock", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--upstream", type=Path, required=True)
        command.add_argument("--bridge", type=Path, required=True)
        if name == "inventory":
            command.add_argument("--observations", type=Path, required=True)
        if name == "record-lock":
            command.add_argument("--reviewed", required=True, help="Reviewed distribution fingerprint from the review command")
        if name == "stage":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--revision", help="Preview-only Git SHA override; defaults to HEAD")
    command = commands.add_parser("verify")
    command.add_argument("--upstream", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--revision", help="Preview-only Git SHA override; defaults to HEAD")
    args = parser.parse_args(arguments)
    try:
        if args.command == "verify":
            count = verify(args.out, validate_revision(args.revision) if args.revision else git_revision(),
                           read_file(args.upstream))
            print(f"Verified {count} exact assets and pack-manifest.json.")
            return
        jars = source_inputs(read_file(args.upstream), read_file(args.bridge))
        if args.command == "inventory":
            inventory = record_inventory(jars, read_file(args.observations))
            (ROOT / INVENTORY).write_bytes(json_bytes(inventory))
            print(f"Recorded {len(inventory['mods'])} observed Fabric mod IDs.")
        elif args.command in {"review", "record-lock"}:
            inventory_raw, _ = load_inventory(jars)
            receipt = distribution_receipt(all_payload(jars), inventory_raw)
            policy = server_policy(receipt["files"])
            reviewed = digest(json_bytes(receipt | policy))
            if args.command == "record-lock":
                require(args.reviewed == reviewed, "Reviewed distribution fingerprint changed")
                (ROOT / DISTRIBUTION_LOCK).write_bytes(json_bytes(receipt))
                (ROOT / SERVER_POLICY).write_bytes(json_bytes(policy))
            print(json_bytes(receipt | policy | {"reviewedDistributionSha256": reviewed}).decode(), end="")
        else:
            count = stage(args.out, validate_revision(args.revision) if args.revision else git_revision(), jars)
            print(f"Staged {count} immutable assets and pack-manifest.json.")
    except (BadZipFile, KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
