from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from forge.stage3_build.bake_projected_texture import build_glove_descriptor


class GloveProjectionBakeTests(unittest.TestCase):
    def manifest(self) -> dict[str, Any]:
        fixture = Path(__file__).parent / "fixtures" / "glove_multiview_valid.json"
        return json.loads(fixture.read_text(encoding="utf-8"))

    def test_valid_glove_emits_immutable_anatomical_bake_contract(self) -> None:
        descriptor = build_glove_descriptor(self.manifest(), "sport-gloves-hedge-maze")
        bake = descriptor["gloveProjectionBake"]

        self.assertEqual(bake["status"], "ready-for-locked-asset")
        self.assertEqual(bake["assetContract"]["derivedRight"]["releaseDeterminant"], 1)
        self.assertTrue(bake["assetContract"]["derivedRight"]["reverseWinding"])
        self.assertFalse(bake["assetContract"]["runtime"]["negativeScale"])

    def test_invalid_glove_requests_input_before_bake(self) -> None:
        manifest = self.manifest()
        manifest["gloveMultiView"]["views"][0]["digits"]["thumb"] = "occluded"

        descriptor = build_glove_descriptor(manifest, "sport-gloves-hedge-maze")

        self.assertEqual(descriptor["gloveProjectionBake"]["reason"], "GLOVE_REQUIRED_DIGIT_NOT_OBSERVED")


if __name__ == "__main__":
    unittest.main()
