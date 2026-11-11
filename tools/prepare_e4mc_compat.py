"""Narrow, deterministic coexistence overlay for the exact bundled e4mc."""

from hashlib import sha256
from io import BytesIO
import json
from struct import unpack_from
from zipfile import ZIP_STORED, ZipFile, ZipInfo


UPSTREAM_SHA256 = "50125e336c383688403e2fb24c5d88af82cd4b64288359ea5323288afe258f95"
CONFIG = "e4mc.mixins.json"
CONFIG_SHA256 = "5b18c0e0905b1495fc163b93a234d947462b756cb7126fdf873e739e49c562ee"
PLAYER_LIST = "link/e4mc/mixin/PlayerListMixin.class"
PLAYER_LIST_SHA256 = "e00ff073ea043dfd16fa2ed7efdfe027e318a55df5959bbd012904e822bd2cb6"
OWNER_METHOD = (
    b"allowOwnerLogin",
    b"(Ljava/net/SocketAddress;Ljava/lang/Object;"
    b"Lorg/spongepowered/asm/mixin/injection/callback/CallbackInfoReturnable;)V",
)
OMIT = {
    "mixins": {
        "BanListCommandsMixin",
        "BanPlayerCommandsMixin",
        "PardonCommandMixin",
        "ServerLoginPacketListenerImplMixin",
    },
    "client": {"ServerNameResolverMixin"},
}


def require_sha(data, expected, name):
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"Unexpected e4mc SHA256 for {name}")


def utf_constants(data):
    count, = unpack_from(">H", data, 8)
    offsets = {3: 4, 4: 4, 5: 8, 6: 8, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
               15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2}
    strings = {}
    offset = 10
    index = 1
    while index < count:
        tag = data[offset]
        offset += 1
        if tag == 1:
            length, = unpack_from(">H", data, offset)
            offset += 2
            strings[index] = data[offset:offset + length]
            offset += length
        else:
            offset += offsets[tag]
        index += 2 if tag in (5, 6) else 1
    return strings, offset


def end_of_member(data, offset):
    attributes, = unpack_from(">H", data, offset + 6)
    offset += 8
    for _ in range(attributes):
        length, = unpack_from(">I", data, offset + 2)
        offset += 6 + length
    return offset


def remove_owner_method(data):
    require_sha(data, PLAYER_LIST_SHA256, PLAYER_LIST)
    strings, offset = utf_constants(data)
    interfaces, = unpack_from(">H", data, offset + 6)
    offset += 8 + 2 * interfaces
    fields, = unpack_from(">H", data, offset)
    offset += 2
    for _ in range(fields):
        offset = end_of_member(data, offset)
    method_count = offset
    methods, = unpack_from(">H", data, method_count)
    offset += 2
    remove = []
    for _ in range(methods):
        start = offset
        access, name, descriptor = unpack_from(">HHH", data, offset)
        offset = end_of_member(data, offset)
        if (strings[name], strings[descriptor]) == OWNER_METHOD:
            if access != 0x0001:
                raise ValueError("Unexpected access flags for e4mc owner bypass")
            remove.append((start, offset))
    if len(remove) != 1:
        raise ValueError("Expected one e4mc PlayerList owner bypass")
    start, end = remove[0]
    return data[:method_count] + (methods - 1).to_bytes(2, "big") + data[method_count + 2:start] + data[end:]


def mixin_config(data):
    require_sha(data, CONFIG_SHA256, CONFIG)
    config = json.loads(data)
    for section, omitted in OMIT.items():
        entries = config[section]
        if not omitted.issubset(entries):
            raise ValueError(f"Unexpected e4mc mixin list {section}")
        config[section] = [entry for entry in entries if entry not in omitted]
    return (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build(upstream):
    """Keep the traditional e4mc relay and the managed Steam permission path."""
    require_sha(upstream, UPSTREAM_SHA256, "author nested JAR")
    result = BytesIO()
    with ZipFile(BytesIO(upstream)) as original, ZipFile(result, "w", ZIP_STORED) as derived:
        replacements = {
            CONFIG: mixin_config(original.read(CONFIG)),
            PLAYER_LIST: remove_owner_method(original.read(PLAYER_LIST)),
        }
        names = original.namelist()
        if len(names) != len(set(names)):
            raise ValueError("e4mc archive contains duplicate members")
        for name in sorted(names):
            member = ZipInfo(name)
            member.create_system = 3
            member.external_attr = ((0o40755 if name.endswith("/") else 0o100644) << 16)
            derived.writestr(member, replacements[name] if name in replacements else original.read(name))
    return result.getvalue()
