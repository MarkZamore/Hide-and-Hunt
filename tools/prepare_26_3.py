"""Prepare the reviewed Steam-only Hide and Hunt for Minecraft 26.3."""

from argparse import ArgumentParser
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

UPSTREAM_SHA256 = "33a9d4215dcc151739df622870cce98135c3126d1db2ecf248d4a7baa0f78db7"
INNER_SHA256 = "d553666404b8ff17b0bd9a9f6d3824020660498a9ecb973dd772f668bc557eab"
MIXIN_SHA256 = "e9b38e481e249496f5536844deefcf4c2e4c4280505a19c7de231d289103c14a"
OUTPUT_NAME = "HideAndHunt-Fabric-1.0.0-beta.2+26.3-lanmc.2.jar"
INNER = "META-INF/jars/HideAndHunt-Fabric-1.0.0-beta.2+26.3.jar"
MIXIN = "de/hideandhunt/mixin/client/EntityRendererMixin.class"
E4MC = "META-INF/jars/e4mc-fabric-6.2.3-modern.jar"
LICENSE = "LICENSE_HideAndHuntMod"
NOTICE = "META-INF/NOTICE-LANMinecraft-26.3.txt"
RETIRED = {
    E4MC,
    "META-INF/licenses/e4mc-LICENSE.txt",
    "de/hideandhunt/PreLaunch.class",
    "de/hideandhunt/mixin/E4mcCommandMixin.class",
    "de/hideandhunt/mixin/client/ChatRelayMixin.class",
}
PROVENANCE = b"""Downstream compatibility overlay for Hide and Hunt by itzmacetekk.
Author bundle: https://modrinth.com/plugin/hide-and-hunt/version/FaWrAGlY
Author SHA256: 33a9d4215dcc151739df622870cce98135c3126d1db2ecf248d4a7baa0f78db7
The Minecraft 26.3 EntityRendererMixin handler ABI was updated.
This JAR contains the Minecraft 26.3 component. Bundled e4mc and author
hooks dedicated to e4mc have been removed. The accompanying pack bridge
removes the relay switch and router forwarding from the hosting flow.
The original author MIT license and Fabric API are included unchanged.
"""


def require_sha(data, expected, label):
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"Unexpected SHA256 for {label}")


def replace_once(data, before, after, label):
    if data.count(before) != 1:
        raise ValueError(f"Unexpected bytecode layout for {label}")
    return data.replace(before, after, 1)


def constant(value):
    return len(value).to_bytes(2, "big") + value


def renderer_mixin(data):
    require_sha(data, MIXIN_SHA256, "EntityRendererMixin")
    arguments = (
        b"(Lnet/minecraft/world/entity/Entity;"
        b"Lnet/minecraft/client/renderer/culling/Frustum;DDD"
    )
    callback = b"Lorg/spongepowered/asm/mixin/injection/callback/CallbackInfoReturnable"
    for suffix in (b";)V", b"<Ljava/lang/Boolean;>;)V"):
        data = replace_once(data, constant(arguments + callback + suffix),
                            constant(arguments + b"F" + callback + suffix), "handler descriptor")
    # The new unused float occupies local 9. Move the callback to 10,
    # retaining the entire original predicate and cancellable result.
    for original, replacement, label in (
        ("0002000a0000002f", "0002000b0000002f", "max locals"),
        ("190903b80032", "190a03b80032", "callback load"),
        ("0000002f004f00500009", "0000002f004f0050000a", "callback local variable"),
        ("0000002f004f00520009", "0000002f004f0052000a", "callback local variable type"),
    ):
        data = replace_once(data, bytes.fromhex(original), bytes.fromhex(replacement), label)
    return data


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def without_mixin(archive, path, group, name):
    config = json.loads(archive.read(path))
    if config[group].count(name) != 1:
        raise ValueError(f"Unexpected {name} entry in {path}")
    config[group].remove(name)
    return json_bytes(config)


def archive_with(source, replacements):
    result = BytesIO()
    with ZipFile(BytesIO(source)) as original, ZipFile(result, "w", ZIP_STORED) as output:
        names = original.namelist()
        additions = {LICENSE, NOTICE}
        if (len(names) != len(set(names)) or set(replacements) - set(names) != additions
                or not RETIRED <= set(names)):
            raise ValueError("The original archive members do not match the overlay")
        for name in sorted((set(names) | additions) - RETIRED):
            member = ZipInfo(name)
            member.create_system = 3
            member.external_attr = ((0o40755 if name.endswith("/") else 0o100644) << 16)
            output.writestr(member, replacements[name] if name in replacements else original.read(name))
    return result.getvalue()


def build(upstream):
    """Return deterministic runtime bytes derived from the exact author JAR."""
    require_sha(upstream, UPSTREAM_SHA256, "author bundle")
    with ZipFile(BytesIO(upstream)) as outer:
        inner = outer.read(INNER)
        license_text = outer.read(LICENSE)
    require_sha(inner, INNER_SHA256, "Minecraft 26.3 author component")
    with ZipFile(BytesIO(inner)) as archive:
        metadata = json.loads(archive.read("fabric.mod.json"))
        relay = {"file": E4MC}
        if (metadata["jars"].count(relay) != 1
                or metadata["entrypoints"].get("preLaunch") != ["de.hideandhunt.PreLaunch"]):
            raise ValueError("Unexpected author relay declarations")
        metadata["jars"].remove(relay)
        del metadata["entrypoints"]["preLaunch"]
        metadata["description"] = "Hide and Hunt for Minecraft 26.3, with Steam multiplayer via LANMinecraft."
        replacements = {
            "fabric.mod.json": json_bytes(metadata),
            "hideandhunt.mixins.json": without_mixin(
                archive, "hideandhunt.mixins.json", "mixins", "E4mcCommandMixin"),
            "hideandhunt.client.mixins.json": without_mixin(
                archive, "hideandhunt.client.mixins.json", "client", "ChatRelayMixin"),
            MIXIN: renderer_mixin(archive.read(MIXIN)),
            LICENSE: license_text,
            NOTICE: PROVENANCE,
        }
    return archive_with(inner, replacements)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidate = build(args.upstream.read_bytes())
    with args.out.open("xb") as output:
        output.write(candidate)
    print(sha256(candidate).hexdigest())


if __name__ == "__main__":
    main()
