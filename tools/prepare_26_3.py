"""Prepare the exact Hide and Hunt beta.2 renderer compatibility overlay."""

from argparse import ArgumentParser
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import prepare_e4mc_compat


UPSTREAM_SHA256 = "33a9d4215dcc151739df622870cce98135c3126d1db2ecf248d4a7baa0f78db7"
INNER_SHA256 = "d553666404b8ff17b0bd9a9f6d3824020660498a9ecb973dd772f668bc557eab"
MIXIN_SHA256 = "e9b38e481e249496f5536844deefcf4c2e4c4280505a19c7de231d289103c14a"
OUTPUT_NAME = "HideAndHunt-Fabric-1.0.0-beta.2+26.3-lanmc.1.jar"
INNER = "META-INF/jars/HideAndHunt-Fabric-1.0.0-beta.2+26.3.jar"
MIXIN = "de/hideandhunt/mixin/client/EntityRendererMixin.class"
E4MC = "META-INF/jars/e4mc-fabric-6.2.3-modern.jar"
NOTICE = "META-INF/NOTICE-LANMinecraft-26.3.txt"
PROVENANCE = b"""Downstream compatibility overlay for Hide and Hunt by itzmacetekk.
Author bundle: https://modrinth.com/plugin/hide-and-hunt/version/FaWrAGlY
Author SHA256: 33a9d4215dcc151739df622870cce98135c3126d1db2ecf248d4a7baa0f78db7
The Minecraft 26.3 EntityRendererMixin handler ABI was updated.
Bundled e4mc retains its ordinary generated-address relay. Its overlapping
admin command and owner-login hooks defer to the managed e4steam component.
Experimental Dialtone resolution and login hooks are disabled.
The original author license and bundled notices are included unchanged.
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


def archive_with(source, replacements):
    result = BytesIO()
    with ZipFile(BytesIO(source)) as original, ZipFile(result, "w", ZIP_STORED) as output:
        names = original.namelist()
        if len(names) != len(set(names)) or set(replacements) - set(names) - {NOTICE}:
            raise ValueError("The original archive members do not match the overlay")
        if NOTICE in names:
            raise ValueError("The original archive already declares a downstream notice")
        for name in sorted(set(names) | set(replacements)):
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
    require_sha(inner, INNER_SHA256, "Minecraft 26.3 author component")
    with ZipFile(BytesIO(inner)) as archive:
        mixin = renderer_mixin(archive.read(MIXIN))
        e4mc = prepare_e4mc_compat.build(archive.read(E4MC))
    return archive_with(upstream, {INNER: archive_with(inner, {MIXIN: mixin, E4MC: e4mc}), NOTICE: PROVENANCE})


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
