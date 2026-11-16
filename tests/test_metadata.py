"""Validate translatable names and repository metadata."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "remotepower"


class MetadataTests(unittest.TestCase):
    def test_manifest(self):
        value = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(value["domain"], "remotepower")
        self.assertTrue(value["config_flow"])

    def test_translations_match(self):
        en = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
        self.assertEqual(
            en, json.loads((INTEGRATION / "translations/en.json").read_text(encoding="utf-8"))
        )
        de = json.loads((INTEGRATION / "translations/de.json").read_text(encoding="utf-8"))

        def keys(value, prefix=""):
            result = set()
            for key, item in value.items():
                path = prefix + "." + key
                result.add(path)
                if isinstance(item, dict):
                    result.update(keys(item, path))
            return result

        self.assertEqual(keys(en), keys(de))
