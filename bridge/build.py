"""Build the exact-pinned Fabric companion without repacking author files."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile


HERE = Path(__file__).resolve().parent
MAVEN = "https://maven.fabricmc.net/"
JAR_NAME = "lanminecraft-hide-and-hunt-bridge-1.0.0.jar"


def checked(payload, sha256, name):
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise ValueError(f"Unexpected SHA256 for {name}")
    return payload


def read_entry(payload, path, sha256):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.namelist().count(path) != 1:
            raise ValueError(f"Expected exactly one entry {path}")
        return checked(archive.read(path), sha256, path)


def library(cache, pin):
    relative = pin["path"]
    destination = cache / relative
    if destination.is_file():
        checked(destination.read_bytes(), pin["sha256"], relative)
        return destination
    with urllib.request.urlopen(MAVEN + relative, timeout=60) as response:
        payload = response.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError(f"Compiler dependency exceeds size limit: {relative}")
    checked(payload, pin["sha256"], relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stage:
        stage_path = Path(stage.name)
        try:
            stage.write(payload)
            stage.close()
            stage_path.replace(destination)
        finally:
            stage_path.unlink(missing_ok=True)
    return destination


def build(client, upstream, out, libraries_root):
    pins = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))
    checked(client.read_bytes(), pins["minecraft"]["sha256"], client.name)
    author = pins["upstream"]
    bundle = checked(upstream.read_bytes(), author["sha256"], upstream.name)
    mod = read_entry(bundle, author["entry"], author["entrySha256"])
    relay = read_entry(mod, author["relayEntry"], author["relayEntrySha256"])

    java_home = os.environ.get("JAVA_HOME")
    if not java_home:
        raise ValueError("Set JAVA_HOME to the verified JDK 25.0.2")
    javac = Path(java_home) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
    compiler = subprocess.check_output([str(javac), "-version"], text=True).strip()
    if compiler != f"javac {pins['compiler']['version']}":
        raise ValueError(f"Unexpected compiler version: {compiler}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bridge-build-", dir=out.parent) as temporary:
        stage = Path(temporary)
        author_jar = stage / "hideandhunt.jar"
        author_jar.write_bytes(mod)
        classpath = [client, author_jar]
        classpath.extend(library(libraries_root, pin) for pin in pins["libraries"])
        classes = stage / "classes"
        classes.mkdir()
        sources = sorted((HERE / "src").rglob("*.java"))
        subprocess.run([
            str(javac), "--release", "25", "-g:none", "-proc:none", "-encoding", "UTF-8",
            "-cp", os.pathsep.join(map(str, classpath)), "-d", str(classes),
            *map(str, sources),
        ], check=True)
        verify = stage / "verification"
        verify.mkdir()
        test_classpath = [classes, *classpath]
        subprocess.run([
            str(javac), "--release", "25", "-g:none", "-proc:none", "-encoding", "UTF-8",
            "-cp", os.pathsep.join(map(str, test_classpath)), "-d", str(verify),
            str(HERE / "verify" / "ExactTargets.java"),
        ], check=True)
        relay_jar = stage / "e4mc.jar"
        relay_jar.write_bytes(relay)
        java = javac.with_name("java.exe" if os.name == "nt" else "java")
        subprocess.run([
            str(java), "-cp", os.pathsep.join(map(str, [verify, *test_classpath])),
            "lanminecraft.hideandhunt.ExactTargets", str(author_jar), str(relay_jar),
        ], check=True)

        resources = HERE / "resources"
        contents = {
            file.relative_to(root).as_posix(): file
            for root in (classes, resources)
            for file in root.rglob("*") if file.is_file()
        }
        contents["META-INF/LICENSE"] = HERE.parent / "LICENSE"
        built = stage / JAR_NAME
        with zipfile.ZipFile(built, "w", compression=zipfile.ZIP_STORED) as archive:
            for path, file in sorted(contents.items()):
                entry = zipfile.ZipInfo(path)
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, file.read_bytes())
        built.replace(out)
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-jar", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--libraries-root", type=Path, help="Shared verified dependency cache")
    args = parser.parse_args()
    if args.out.name != JAR_NAME:
        parser.error(f"Output must be named {JAR_NAME}")
    try:
        output = args.out.resolve()
        libraries_root = args.libraries_root or output.parent / "bridge-libraries"
        sha256 = build(args.client_jar.resolve(), args.upstream.resolve(), output, libraries_root.resolve())
        print(f"{sha256}  {args.out}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
