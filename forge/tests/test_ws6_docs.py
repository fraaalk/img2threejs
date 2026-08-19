#!/usr/bin/env python3
"""WS6 documentation and version metadata guard tests."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GRIMOIRE_BUILD = ROOT / "grimoire" / "build"
SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
PACKAGE_JSON = ROOT / "package.json"

# Both release paths anchor the version key at column zero: `scripts/release_metadata.py` with
# VERSION_PATTERN, and `.github/workflows/beta-release.yml` with an equivalent sed. Accept the
# stable and the beta spellings the beta workflow round-trips between.
SKILL_VERSION_PATTERN = re.compile(r"^version: (\d+\.\d+\.\d+(?:-beta\.\d+)?)$", re.MULTILINE)
README_BADGE_PATTERN = re.compile(r"version-(\d+\.\d+\.\d+(?:-beta\.\d+)?)-green\.svg")


class Ws6DocsTest(unittest.TestCase):
    def test_ws6_docs_exist(self) -> None:
        for relative_path in (
            "implicit_sdf_modeling.md",
            "visual_hull_reconstruction.md",
            "subdivision_surfaces.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((GRIMOIRE_BUILD / relative_path).exists())

    def test_fitting_doc_mentions_divine_eye_loop(self) -> None:
        text = (GRIMOIRE_BUILD / "analysis_by_synthesis_fitting.md").read_text(encoding="utf-8")
        for marker in (
            "fit_against_divine_eye()",
            "correction_loop.decide()",
            "bestRawFidelity",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_skill_version_is_reachable_by_the_release_tooling(self) -> None:
        """Assert against the real SKILL.md, never a fixture.

        Nesting the key under a `metadata:` parent is valid YAML and reads fine to a human, so it
        survived review; both release paths then match nothing and abort -- the beta workflow with
        "SKILL.md must contain one supported version field", `release_metadata.py` with
        "must contain exactly one replaceable version". A fixture-only test cannot see that,
        because the fixture is the shape the tooling wants rather than the shape on disk.
        """
        match = SKILL_VERSION_PATTERN.search(SKILL.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            match,
            "SKILL.md needs one unindented `version:` front-matter key for the release tooling",
        )

    def test_readme_declares_one_version_badge_matching_the_skill(self) -> None:
        """A duplicated badge block let README carry two different versions at once.

        `release_metadata.py` rewrites with count=1, so a second badge is never updated and goes
        stale silently. Pin the count as well as the value.
        """
        skill_match = SKILL_VERSION_PATTERN.search(SKILL.read_text(encoding="utf-8"))
        assert skill_match is not None  # the test above reports this failure properly
        badges = README_BADGE_PATTERN.findall(README.read_text(encoding="utf-8"))

        self.assertEqual(len(badges), 1, f"README must declare exactly one version badge, got {badges}")
        self.assertEqual(badges[0], skill_match.group(1))

    def test_changelog_defines_each_link_reference_once(self) -> None:
        """A merge kept both sides' link blocks, so six versions had two definitions each.

        Markdown silently resolves the first and ignores the rest, so half the block was dead text
        pointing at a different organisation than the live one -- invisible in the rendered page.
        Deliberately not asserting heading order: `update_changelog` inserts above the first `## [`,
        so a test pinning `Unreleased` to the top would fail on the first automated release.
        """
        labels = re.findall(r"^\[([^\]]+)\]:", CHANGELOG.read_text(encoding="utf-8"), re.MULTILINE)
        duplicates = sorted({label for label in labels if labels.count(label) > 1})

        self.assertEqual(duplicates, [], f"CHANGELOG.md defines these link references twice: {duplicates}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# --- installer repo invariants -------------------------------------------------------------
#
# The installer's user-facing contract lives partly in files `openspec/` cannot hold, because
# `openspec/` is gitignored. These assertions are that contract, checked against the real files.

LIFECYCLE_SCRIPTS = ("preinstall", "install", "postinstall", "prepare")

# `npx <bare-name>` resolves the npm registry at invocation time, and `img2threejs` is unregistered.
# Allowed: `npx img2threejs/img2threejs` (GitHub shorthand) and `github:img2threejs/img2threejs`.
BARE_NPX_PATTERN = re.compile(r"\bnpx\s+(?:-y\s+)?img2threejs(?!/)")

# The instruction the installer exists to replace: it materialises a full checkout inside one host's
# skills directory, which is the drift `CLAUDE.md` forbids.
CLONE_INTO_HOST_PATTERN = re.compile(r"git clone[^\n]*~/\.(?:config/)?[a-z0-9-]+/(?:[a-z0-9-]+/)?skills")

RUNTIME_EXECUTABLE_PATTERN = re.compile(r"runtime/[A-Za-z0-9_./-]+\.(?:mjs|js|py|ts)")
RUNTIME_NOT_SHIPPED = "not shipped with the repository"


def _tracked(pattern: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / rel for rel in out]


class InstallerRepoInvariantsTest(unittest.TestCase):
    def test_package_version_matches_the_skill_version(self) -> None:
        """One version source. `npm install` tolerates a manifest with no `version`, but `npm pack`
        rejects it, so the field cannot simply be dropped -- it has to be kept honest instead."""
        skill_match = SKILL_VERSION_PATTERN.search(SKILL.read_text(encoding="utf-8"))
        assert skill_match is not None
        package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

        self.assertEqual(
            package.get("version"),
            skill_match.group(1),
            "package.json version must equal SKILL.md's; nothing in CI syncs them for you",
        )

    def test_package_declares_no_lifecycle_scripts(self) -> None:
        """npm runs `prepare` automatically when installing a git dependency, so a lifecycle script
        here executes on every `npx` invocation, on a stranger's machine, unauthenticated."""
        package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})

        for hook in LIFECYCLE_SCRIPTS:
            with self.subTest(hook=hook):
                self.assertNotIn(hook, scripts)

    def test_no_document_prints_the_bare_npx_form(self) -> None:
        """The npm name is unregistered; a documented bare form is a live code-execution path for
        whoever registers it next."""
        for path in _tracked("*.md"):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(BARE_NPX_PATTERN.search(path.read_text(encoding="utf-8")))

    def test_no_document_instructs_cloning_into_a_host_skills_directory(self) -> None:
        for path in _tracked("*.md"):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(CLONE_INTO_HOST_PATTERN.search(path.read_text(encoding="utf-8")))

    def test_host_enumerations_are_complete(self) -> None:
        """SKILL.md claims the skill is agent-agnostic across Claude, Codex and OpenCode, but both
        entrypoint listings named only the first two."""
        for path in (README, SKILL):
            with self.subTest(path=path.name):
                self.assertIn("opencode/skills", path.read_text(encoding="utf-8"))

    def test_dependency_claims_name_the_installer_prerequisites(self) -> None:
        """`README.md` said "nothing to install"; the lead install path needs Node and git."""
        text = README.read_text(encoding="utf-8")
        for marker in ("Node", "git"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_documented_runtime_paths_are_tracked_or_declared_external(self) -> None:
        """`runtime/` is gitignored with zero tracked files, so every clone the installer produces
        would otherwise carry a documented step that cannot run."""
        for path in _tracked("*.md"):
            text = path.read_text(encoding="utf-8")
            refs = set(RUNTIME_EXECUTABLE_PATTERN.findall(text))
            if not refs:
                continue
            missing = sorted(ref for ref in refs if not (ROOT / ref).exists())
            if not missing:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(
                    RUNTIME_NOT_SHIPPED,
                    text,
                    f"{path.relative_to(ROOT)} references {missing} but ships no such file",
                )
