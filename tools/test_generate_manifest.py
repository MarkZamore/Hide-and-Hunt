import io
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import generate_manifest as manifest


def tiny_jar(mod_id, version):
    payload = io.BytesIO()
    with ZipFile(payload, "w") as jar:
        jar.writestr("fabric.mod.json", json.dumps({"id": mod_id, "version": version}))
    return payload.getvalue()


class ManifestTests(unittest.TestCase):
    def test_asset_zip_is_ordinal_and_byte_stable(self):
        first = manifest.zip_root({"launcher/z.txt": b"z", "launcher/a.txt": b"a"})
        second = manifest.zip_root({"launcher/a.txt": b"a", "launcher/z.txt": b"z"})
        self.assertEqual(first, second)
        with ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(), ["launcher/a.txt", "launcher/z.txt"])
            self.assertEqual(archive.read("launcher/a.txt"), b"a")
            self.assertEqual(archive.getinfo("launcher/a.txt").date_time, (1980, 1, 1, 0, 0, 0))

    def test_same_size_replacement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Size/SHA256 mismatch"):
            manifest.check_pin(b"bad", manifest.fingerprint(b"jar"), "reviewed test asset")

    def test_native_inventory_tracks_only_selected_author_versions(self):
        jars = {"mods/author.jar": tiny_jar("hideandhunt", "beta"),
                "mods/other.jar": tiny_jar("hideandhunt", "alpha")}
        observations = {"minecraft": "26.3", "fabricloader": "0.20.1", "java": "25",
                        "mixinextras": "0.5.5", "e4steam": "0.3.4+modern", "hideandhunt": "beta"}
        with patch.object(manifest, "PACK_IDS", {"hideandhunt"}):
            inventory = manifest.record_inventory(jars, manifest.json_bytes(observations))
            self.assertEqual(inventory["mods"], [
                {"id": "hideandhunt", "name": "hideandhunt", "version": "beta", "source": "mods/author.jar"}])
            self.assertEqual(inventory["managedInfrastructure"]["e4steam"], "0.3.4+modern")
            observations["hideandhunt"] = "unknown"
            with self.assertRaisesRegex(ValueError, "Unexpected native mod/version"):
                manifest.record_inventory(jars, manifest.json_bytes(observations))


if __name__ == "__main__":
    unittest.main()
