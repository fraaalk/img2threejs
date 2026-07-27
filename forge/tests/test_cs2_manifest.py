from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from forge.stage1_intake.cs2_manifest import (
    apply_confirmation,
    build_classification_record,
    build_manifest,
    normalize_manifest,
    persist_manifest,
    record_retrieval_outcome,
    validate_manifest,
)


def write_png(path: Path, width: int = 128, height: int = 128) -> None:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            value = 40 if 28 <= x < 100 and 12 <= y < 116 else 240
            row.extend((value, value, value))
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    payload = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", payload) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Cs2ManifestTests(unittest.TestCase):
    def test_primary_only_without_name_proceeds_generically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "knife.png"
            write_png(reference)
            manifest = build_manifest(reference, None)
            self.assertEqual(manifest["state"], "proceed")
            self.assertEqual(manifest["exactnessTier"], "image-only")
            self.assertEqual(manifest["primaryImage"]["role"], "primary")
            self.assertIsNone(manifest["resolvedIdentity"])
            self.assertIsNone(manifest["genericHandoff"]["componentAdapter"])
            self.assertTrue(validate_manifest(manifest))

    def test_candidate_is_not_an_adapter_until_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "knife.png"
            write_png(reference)
            classification = build_classification_record(
                "knife", "karambit", 0.98, ["view:front:subject"], provider="offline-fixture"
            )
            manifest = build_manifest(reference, classification)
            self.assertEqual(manifest["state"], "proceed")
            self.assertEqual(manifest["identityDecision"]["status"], "provisional")
            self.assertNotIn("componentAdapter", manifest)
            accepted = apply_confirmation(manifest, "accept", manifest["identityCandidates"][0]["id"])
            self.assertEqual(accepted["identityDecision"]["status"], "accepted")
            self.assertEqual(accepted["componentAdapter"], "cs2-knife-v1")
            self.assertTrue(validate_manifest(manifest))

    def test_unknown_subtype_is_explicitly_unsupported_without_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "rifle.png"
            write_png(reference)
            classification = build_classification_record("rifle", "ak47", 0.99, ["view:front:subject"])
            manifest = build_manifest(reference, classification)
            accepted = apply_confirmation(manifest, "accept", manifest["identityCandidates"][0]["id"])
            self.assertEqual(accepted["state"], "request-input")
            self.assertEqual(accepted["identityDecision"]["status"], "unsupported-subtype")
            self.assertNotIn("componentAdapter", manifest)
            self.assertNotIn("componentAdapter", accepted)

    def test_glock_and_awp_acceptance_uses_family_qualified_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "weapon.png"
            write_png(reference)
            for family, subtype, adapter in (
                ("pistol", "glock-18", "cs2-pistol-v1"),
                ("rifle", "awp", "cs2-rifle-v1"),
            ):
                manifest = build_manifest(reference, build_classification_record(family, subtype, 0.99, ["view:front:subject"]))
                accepted = apply_confirmation(manifest, "accept", manifest["identityCandidates"][0]["id"])
                self.assertEqual(accepted["componentAdapter"], adapter)
                self.assertEqual(accepted["resolvedIdentity"]["itemFamily"], family)
                self.assertEqual(accepted["resolvedIdentity"]["subtype"], subtype)

    def test_bad_secondary_preserves_primary_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "primary.png"
            secondary = Path(directory) / "secondary.png"
            write_png(primary)
            secondary.write_bytes(b"not-an-image")
            manifest = build_manifest(primary, secondary_image=secondary)
            self.assertEqual(manifest["state"], "proceed")
            self.assertTrue(manifest["secondaryAssociation"]["replacementRequested"])
            self.assertEqual(manifest["secondaryAssociation"]["status"], "contradicted")

    def test_confirmation_and_retrieval_failure_are_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "unknown.png"
            write_png(reference)
            manifest = apply_confirmation(build_manifest(reference), "continue-generically")
            self.assertEqual(manifest["identityDecision"]["status"], "skipped")
            failed = record_retrieval_outcome(manifest, "error", "index-unavailable")
            self.assertEqual(failed["state"], "proceed")
            self.assertEqual(failed["enrichment"]["retrieval"]["status"], "not-eligible")

    def test_v1_normalization_selects_legacy_first_source_as_primary(self) -> None:
        legacy = {"schemaVersion": 1, "state": "proceed", "sourceViews": [{"role": "reference", "path": "legacy.png"}], "route": "procedural-finish", "exactnessTier": "image-only", "warnings": []}
        normalized = normalize_manifest(legacy)
        self.assertEqual(normalized["primaryImage"]["path"], "legacy.png")
        self.assertEqual(normalized["primaryImage"]["role"], "primary")

    def test_manifest_write_is_atomic_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "knife.png"
            output = Path(directory) / "cs2-intake.json"
            write_png(reference)
            manifest = build_manifest(reference)
            persist_manifest(manifest, output)
            self.assertEqual(json.loads(output.read_text())["schemaVersion"], 2)
            brief = output.parent / "cs2-internal-brief.json"
            self.assertEqual(json.loads(brief.read_text())["authority"], "report-only")
            self.assertFalse(output.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
