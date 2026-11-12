"""Run the actual pinned Fabric client in a single disposable QA fixture."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import file_digest, md5, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from threading import Thread
from urllib.parse import quote
from urllib.request import urlopen
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile
from zlib import compress, crc32


MC = "26.3"
FABRIC = "0.20.1"
BASE_META = "9f67e10ed013deeaad20ac3c800652765d493408"
FABRIC_META = "d4398cf497ce8a3b690439dd0f54bdd2f583a4621c543aca83cc13613206b0ed"
FABRIC_LOADER = "d0c5a082e07410aaff9de7ab196aa6b4236002870f9ba3ad5c1260fcce5110ad"
UPSTREAM_NAME = "HideAndHunt-Fabric-1.0.0-beta.2+26.1-26.3.jar"
UPSTREAM_SHA = "33a9d4215dcc151739df622870cce98135c3126d1db2ecf248d4a7baa0f78db7"
STEAM_NAME = "e4steam-fabric-quilt-mc26.1-26.3-v0.3.4-lanmc-native-ui.2.jar"
STEAM_SHA = "248fe6c4bf8f4decd0eea2c0883f15559eedd7491e6a9b5859b3bd1cafdcb26d"
QA_USER = "HideHuntQA"
OWNER = "Hide and Hunt native QA"
PACK = Path(__file__).resolve().parents[3]


def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def matches(path, digest, algorithm, size=None):
    if not path.is_file() or size is not None and path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return file_digest(stream, algorithm).hexdigest() == digest


def exact_get(url, destination, digest, algorithm="sha256", size=None):
    if matches(destination, digest, algorithm, size):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".download")
    try:
        with urlopen(url, timeout=45) as response:
            if urlsplit(response.url).scheme != "https":
                raise ValueError("The download left HTTPS")
            limit = size if size is not None else 20 * 1024 * 1024
            with partial.open("wb") as target:
                while chunk := response.read(min(1024 * 1024, limit - target.tell() + 1)):
                    target.write(chunk)
                    if target.tell() > limit:
                        raise ValueError(f"Download exceeds its expected size: {url}")
        if not matches(partial, digest, algorithm, size):
            raise ValueError(f"Incorrect downloaded bytes: {url}")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def exact_cached(cache, destination, remote, *, link=False):
    size = remote.get("size")
    digest = remote["sha1"]
    if matches(cache, digest, "sha1", size):
        if not link:
            return cache
        if not matches(destination, digest, "sha1", size):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.unlink(missing_ok=True)
            os.link(cache, destination)
        return destination
    return exact_get(remote["url"], destination, digest, "sha1", size)


def allowed(rules, features=()):
    if not rules:
        return True
    result = False
    for rule in rules:
        condition = rule.get("os", {})
        if condition.get("name", "windows") != "windows":
            continue
        if condition.get("arch", "x86_64") not in {"x86_64", "amd64", "x64"}:
            continue
        windows = ".".join(map(str, sys.getwindowsversion().platform_version))
        if condition.get("version") and not re.search(condition["version"], windows):
            continue
        if any((key in features) != value for key, value in rule.get("features", {}).items()):
            continue
        result = rule["action"] == "allow"
    return result


def arguments(values, features=()):
    for value in values:
        if isinstance(value, str):
            yield value
        elif allowed(value["rules"], features):
            resolved = value["value"]
            yield from ([resolved] if isinstance(resolved, str) else resolved)


def coordinate(name):
    group, artifact, version, *classifiers = name.split(":")
    filename = f"{artifact}-{version}" + (f"-{classifiers[0]}" if classifiers else "") + ".jar"
    return "/".join((group.replace(".", "/"), artifact, version, filename))


def create_fixture(workspace, root):
    workspace = workspace.resolve(strict=True)
    expected = workspace / "artifacts" / "agent-runs"
    if expected.resolve(strict=True) != expected or root.absolute() != root.resolve():
        raise ValueError("Refusing a redirected QA fixture")
    if not root.is_relative_to(expected) or root == expected:
        raise ValueError("QA fixture must be beneath the workspace artifacts/agent-runs")
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "RUN.json"
    if not marker.exists():
        if any(root.iterdir()):
            raise ValueError("QA fixture is nonempty without an ownership record")
        now = datetime.now(timezone.utc)
        json_write(marker, {
            "owner": OWNER,
            "purpose": "One real Fabric instance with synthetic local worlds and skins",
            "createdAt": now.isoformat(),
            "deleteBy": (now + timedelta(hours=20)).isoformat(),
            "expectedMaxBytes": 2 * 1024**3,
            "keep": ["redacted native mod registry", "compact native acceptance report"],
        })
    elif json.loads(marker.read_text(encoding="utf-8"))["owner"] != OWNER:
        raise ValueError("The QA fixture belongs to another task")


def prepare(workspace, root):
    shared = workspace / "Minecraft/Launcher/Shared"
    metadata = root / "metadata"
    base = json.loads(exact_get(
        f"https://piston-meta.mojang.com/v1/packages/{BASE_META}/{MC}.json",
        metadata / "minecraft.json", BASE_META, "sha1",
    ).read_text(encoding="utf-8"))
    profile = json.loads(exact_get(
        f"https://meta.fabricmc.net/v2/versions/loader/{MC}/{FABRIC}/profile/json",
        metadata / "fabric.json", FABRIC_META,
    ).read_text(encoding="utf-8"))
    if base["id"] != MC or profile["id"] != f"fabric-loader-{FABRIC}-{MC}" or profile["inheritsFrom"] != MC:
        raise ValueError("Unexpected native runtime profile")
    client = exact_cached(shared / f"versions/{MC}/{MC}.jar", root / "runtime/minecraft.jar", base["downloads"]["client"])
    asset = base["assetIndex"]
    index = exact_cached(shared / f"assets/indexes/{asset['id']}.json",
                         root / f"assets/indexes/{asset['id']}.json", asset, link=True)
    objects = {obj["hash"]: obj["size"] for obj in json.loads(index.read_text(encoding="utf-8"))["objects"].values()}

    def stage_asset(row):
        digest, size = row
        relative = f"objects/{digest[:2]}/{digest}"
        exact_cached(shared / "assets" / relative, root / "assets" / relative, {
            "sha1": digest,
            "size": size,
            "url": f"https://resources.download.minecraft.net/{digest[:2]}/{digest}",
        }, link=True)

    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(stage_asset, objects.items()))

    libraries = []
    for entry in profile["libraries"]:
        relative = coordinate(entry["name"])
        digest = entry.get("sha256", FABRIC_LOADER)
        existing = shared / "libraries" / relative
        libraries.append(existing if matches(existing, digest, "sha256", entry.get("size")) else exact_get(
            entry["url"] + quote(relative, safe="/"), root / "runtime/libraries" / relative,
            digest, size=entry.get("size"),
        ))
    for entry in base["libraries"]:
        if not allowed(entry.get("rules")):
            continue
        artifact = entry["downloads"]["artifact"]
        relative = artifact["path"]
        libraries.append(exact_cached(shared / "libraries" / relative, root / "runtime/libraries" / relative, artifact))
    libraries.append(client)
    return base, profile, libraries


def stage_game(root, content, bridge):
    game = root / "game"
    mods = game / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    retired = json.loads((PACK / "tools/retired-files.json").read_text(encoding="utf-8"))
    if content is not None:
        retired.append({"path": f"mods/{UPSTREAM_NAME}", "sha256": UPSTREAM_SHA, "sizeBytes": 23831177})
    for row in retired:
        if not row["path"].startswith("mods/"):
            continue
        previous = mods / Path(row["path"]).name
        if previous.exists():
            if not matches(previous, row["sha256"], "sha256", row["sizeBytes"]):
                raise ValueError(f"Unexpected bytes in previous QA mod: {previous.name}")
            previous.unlink()
    if content is None:
        exact_get("https://cdn.modrinth.com/data/M5kGx3Is/versions/FaWrAGlY/" + quote(UPSTREAM_NAME),
                  mods / UPSTREAM_NAME, UPSTREAM_SHA, size=23831177)
    else:
        shutil.copyfile(content, mods / content.name)
    config = game / "config"
    (config / "e4steam").mkdir(parents=True, exist_ok=True)
    if bridge:
        shutil.copyfile(bridge, mods / bridge.name)
        exact_get("https://github.com/MarkZamore/e4steam/releases/download/native-lan-ui-v2/" + STEAM_NAME,
                  mods / STEAM_NAME, STEAM_SHA, size=3798124)
        shutil.copyfile(PACK / "config/log4j2.xml", config / "log4j2.xml")
    else:
        (mods / STEAM_NAME).unlink(missing_ok=True)
    # Keep the QA instance from registering a live Steam host.
    (config / "e4steam/e4steam.toml").write_text("hostEnabled = false\n", encoding="utf-8")
    return game


def compile_agent(jdk, root, libraries):
    source = Path(__file__).with_name("InventoryAgent.java")
    compiled = root / "qa-agent/classes"
    compiled.mkdir(parents=True, exist_ok=True)
    asm = next(file for file in libraries if file.name == "asm-9.10.1.jar")
    subprocess.run([jdk / "bin/javac.exe", "--release", "25", "-classpath", asm,
                    "-d", compiled, source], check=True)
    archive = root / "qa-agent/inventory-agent.jar"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nPremain-Class: InventoryAgent\r\n\r\n")
        for path in sorted(compiled.glob("InventoryAgent*.class")):
            output.write(path, path.name)
    return archive


def java_arg(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def synthetic_skin():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc32(kind + data))

    header = struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)
    pixels = b"".join(
        b"\0" + b"".join(b"\x16\xce\x90" if (x // 8 + y // 8) % 2 else b"\xef\x6e\x20" for x in range(64))
        for y in range(64)
    )
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", compress(pixels)) + chunk(b"IEND", b"")


def run(workspace, root, jdk, label, content, bridge, adapter_args):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
        raise ValueError("Invalid evidence label")
    evidence = root / "evidence" / label
    evidence.mkdir(parents=True, exist_ok=False)
    base, profile, libraries = prepare(workspace, root)
    game = stage_game(root, content, bridge)
    pack_args = []
    if bridge:
        pack_args = [arg for arg in (PACK / "launcher/jvm-args.txt").read_text(encoding="utf-8").splitlines()
                     if arg and not arg.startswith("#")]
    agent = compile_agent(jdk, root, libraries)
    temp = root / "temp"
    home = root / "home"
    for path in (temp, home, temp / "java", temp / "jna", temp / "lwjgl", temp / "netty"):
        path.mkdir(parents=True, exist_ok=True)
    json_write(evidence / "pins.json", {
        "minecraftMetadataSha1": BASE_META, "fabricMetadataSha256": FABRIC_META,
        "authorBundleSha256": UPSTREAM_SHA,
        "runtimeContentSha256": sha256(content.read_bytes()).hexdigest() if content else UPSTREAM_SHA,
        "qaBridgeSha256": sha256(bridge.read_bytes()).hexdigest() if bridge else None,
        "steamJarSha256": STEAM_SHA if bridge else None,
        "actualSteamSession": "NOT RUN",
    })

    player = UUID(bytes=md5(f"OfflinePlayer:{QA_USER}".encode()).digest(), version=3)
    skin = synthetic_skin()
    skin_hash = sha256(skin).hexdigest()
    skin_path = f"/skin/{player}/{skin_hash}"

    class SkinServer(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == skin_path:
                with (evidence / "skin-requests.log").open("a", encoding="utf-8") as output:
                    output.write(skin_hash + "\n")
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(skin)))
                self.end_headers()
                self.wfile.write(skin)
                return
            self.send_error(404)

        def log_message(self, format, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), SkinServer) as skins:
        thread = Thread(target=skins.serve_forever, daemon=True)
        thread.start()
        identity_args = []
        if adapter_args:
            registry = evidence / "skin-registry.txt"
            registry.write_text(f"{player}|{skin_hash}|classic|http://127.0.0.1:{skins.server_port}{skin_path}\n",
                                encoding="utf-8")
            identity_args = [
                f"-Dminecraft.portable.skin.registry={registry}",
                f"-Dminecraft.portable.identity.localPlayer={player}",
            ]
        values = {
            "natives_directory": temp, "launcher_name": "LANMinecraft-QA", "launcher_version": "1",
            "classpath": os.pathsep.join(map(str, libraries)), "auth_player_name": QA_USER,
            "version_name": profile["id"], "game_directory": game, "assets_root": root / "assets",
            "assets_index_name": base["assets"], "auth_uuid": player.hex,
            "auth_access_token": "0", "clientid": "", "auth_xuid": "",
            "version_type": "release", "resolution_width": 1120, "resolution_height": 630,
        }

        def resolve(value):
            return re.sub(r"\$\{([^}]+)\}", lambda match: str(values[match[1]]), value)

        args = [
            "-Xms1G", "-Xmx3G", "-Duser.home=" + str(home), "-Djava.io.tmpdir=" + str(temp),
            "-Dfile.encoding=UTF-8", "-Djava.net.preferIPv4Stack=true",
            "-XX:ErrorFile=" + str(evidence / "hs_err_pid%p.log"),
            f"-javaagent:{agent}={evidence / 'mod-versions.json'}",
            *adapter_args,
            *identity_args,
            *pack_args,
            *map(resolve, arguments(base["arguments"]["jvm"])),
            *map(resolve, arguments(profile["arguments"]["jvm"])),
            profile["mainClass"],
            *map(resolve, arguments(base["arguments"]["game"], {"has_custom_resolution"})),
        ]
        argfile = evidence / "java-args.txt"
        argfile.write_text("\n".join(map(java_arg, args)) + "\n", encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if not key.lower().startswith("steam")}
        for key in ("TMP", "TEMP", "APPDATA", "LOCALAPPDATA"):
            env[key] = str(temp)
        with (evidence / "console.log").open("wb") as output:
            child = subprocess.Popen([jdk / "bin/java.exe", f"@{argfile}"], cwd=game, env=env,
                                     stdout=output, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"QA_GAME_STARTED pid={child.pid} label={label}", flush=True)
            try:
                exit_code = child.wait()
                json_write(evidence / "exit.json", {"exitCode": exit_code})
                return exit_code
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=20)
                skins.shutdown()
                thread.join(timeout=5)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--jdk", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--content", type=Path)
    parser.add_argument("--bridge", type=Path)
    parser.add_argument("--adapter-args", type=Path, help="JSON array of freshly prepared JVM options")
    options = parser.parse_args()
    root = options.fixture.absolute()
    create_fixture(options.workspace, root)
    adapter_args = json.loads(options.adapter_args.read_text(encoding="utf-8")) if options.adapter_args else []
    raise SystemExit(run(options.workspace.resolve(strict=True), root, options.jdk.resolve(strict=True),
                         options.label, options.content, options.bridge, adapter_args))


if __name__ == "__main__":
    main()
