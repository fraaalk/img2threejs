#!/usr/bin/env python3
"""End-to-end tests for the `img2threejs` installer CLI.

Every case drives the real `bin/cli.mjs` through a subprocess, because the thing under test is what
lands on the filesystem, not what a function returns. Assertions therefore check the exit code plus
`islink`/`realpath`, never message text: a prose assertion passes while the filesystem is wrong and
breaks the moment the wording changes.

Hermetic by construction. Every subprocess runs with HOME, XDG_CONFIG_HOME, IMG2THREEJS_HOME and
IMG2THREEJS_REPO_URL redirected into a temporary directory, and `test_zzz_real_home_untouched`
asserts the developer's real entrypoints are byte-identical afterwards. `os.homedir()` honours HOME
and `os.userInfo().homedir` does not, so the CLI is also asserted never to call the latter.

Node and git are hard requirements, matching the nine existing modules that shell out to `node`
without a skip guard. A missing binary fails; it never silently reduces coverage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin" / "cli.mjs"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2
EXIT_NEEDS_INPUT = 3

# GitHub runners have no configured identity, so every commit passes one inline. Without this the
# fixture build fails with "Author identity unknown" -- green locally, red in CI.
GIT_IDENTITY = [
    "-c", "user.name=img2threejs test",
    "-c", "user.email=test@img2threejs.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "init.defaultBranch=main",
]

REAL_ENTRYPOINTS = (
    Path.home() / ".claude" / "skills" / "img2threejs",
    Path.home() / ".codex" / "skills" / "img2threejs",
    Path.home() / ".config" / "opencode" / "skills" / "img2threejs",
)


def _real_entrypoint_state() -> dict[str, str]:
    state = {}
    for path in REAL_ENTRYPOINTS:
        if path.is_symlink():
            state[str(path)] = f"symlink:{os.readlink(path)}"
        elif path.exists():
            state[str(path)] = "directory" if path.is_dir() else "file"
        else:
            state[str(path)] = "absent"
    return state


def git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *GIT_IDENTITY, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class InstallerTestCase(unittest.TestCase):
    """Shared fixture: a local git remote plus a fake home, both inside a temp directory."""

    @classmethod
    def setUpClass(cls) -> None:
        for binary in ("node", "git"):
            if shutil.which(binary) is None:
                raise AssertionError(
                    f"{binary} is required to test the installer; this must fail, not skip, "
                    "or a missing binary silently reduces coverage"
                )
        cls.baseline_real_state = _real_entrypoint_state()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.home = self.tmp / "home"
        self.state_home = self.tmp / "state"
        self.origin = self.tmp / "origin"
        self.home.mkdir()
        self._build_origin()

    def _build_origin(self) -> None:
        """A real repository with the shape the integrity manifest requires and a mixed tag set."""
        self.origin.mkdir()
        (self.origin / "forge").mkdir()
        (self.origin / "grimoire").mkdir()
        (self.origin / "forge" / "keep.txt").write_text("forge\n", encoding="utf-8")
        (self.origin / "grimoire" / "keep.txt").write_text("grimoire\n", encoding="utf-8")

        git(["init", "-q", "."], self.origin)
        # A partial clone needs the source to advertise the filter over file:// transport.
        git(["config", "uploadpack.allowfilter", "true"], self.origin)

        # `beta-release.yml` emits three-component prereleases (X.Y.Z-beta.N); the two beta tags
        # currently on origin (v1.5-beta, v1.5-beta.0) predate that and carry only two components,
        # so the fixture holds both shapes and the conforming one must win.
        for version, tag in (("1.4.0", "v1.4.0"), ("1.4.3", "v1.4.3"), ("1.5.0-beta.1", "v1.5.0-beta.1")):
            (self.origin / "SKILL.md").write_text(
                f"---\nname: img2threejs\nversion: {version}\n---\n", encoding="utf-8"
            )
            git(["add", "-A"], self.origin)
            git(["commit", "-qm", f"release {version}"], self.origin)
            git(["tag", "-a", tag, "-m", tag], self.origin)

        # Legacy tags the governed pattern must skip rather than choke on.
        git(["tag", "-a", "v1.0", "-m", "v1.0"], self.origin)
        git(["tag", "-a", "v1.5-beta.0", "-m", "v1.5-beta.0"], self.origin)

        # main moves past the last release so "stable" cannot accidentally mean HEAD.
        (self.origin / "SKILL.md").write_text(
            "---\nname: img2threejs\nversion: 1.5.1\n---\n", encoding="utf-8"
        )
        git(["add", "-A"], self.origin)
        git(["commit", "-qm", "unreleased work on main"], self.origin)

    def env(self, **overrides: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / ".config"),
                "IMG2THREEJS_HOME": str(self.state_home),
                "IMG2THREEJS_REPO_URL": f"file://{self.origin}",
            }
        )
        env.update(overrides)
        return env

    def run_cli(self, *args: str, stdin: str | None = None, **env_overrides: str):
        return subprocess.run(
            ["node", str(CLI), *args],
            input="" if stdin is None else stdin,
            capture_output=True,
            text=True,
            env=self.env(**env_overrides),
        )

    def detect(self, *hosts: str) -> None:
        """Create each host's config root, which is the pinned detection predicate."""
        roots = {
            "claude": self.home / ".claude",
            "codex": self.home / ".codex",
            "opencode": self.home / ".config" / "opencode",
        }
        for host in hosts:
            roots[host].mkdir(parents=True, exist_ok=True)

    @property
    def canonical(self) -> Path:
        return self.state_home / "repo"

    def claude_target(self) -> Path:
        return self.home / ".claude" / "skills" / "img2threejs"

    def clone_into(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        git(["clone", "-q", f"file://{self.origin}", str(dest)], self.tmp)


class ChannelResolutionTest(InstallerTestCase):
    def test_stable_resolves_the_newest_conforming_release_not_head(self) -> None:
        """v1.5-beta.0 and v1.0 do not match `v<major>.<minor>.<patch>`; v1.4.3 does."""
        self.detect("claude")
        result = self.run_cli("install", "claude", "--yes", "--json")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertEqual(payload["ref"], "v1.4.3")
        self.assertEqual(payload["version"], "1.4.3")
        for legacy in ("v1.0", "v1.5-beta.0", "v1.5.0-beta.1"):
            self.assertIn(legacy, payload["skippedTags"])

    def test_beta_channel_selects_the_prerelease_line(self) -> None:
        self.detect("claude")
        result = self.run_cli("install", "claude", "--yes", "--channel", "beta", "--json")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertEqual(payload["ref"], "v1.5.0-beta.1")
        # The two-component legacy spelling is skipped, not preferred for sorting later.
        self.assertIn("v1.5-beta.0", payload["skippedTags"])

    def test_main_channel_is_an_explicit_opt_in(self) -> None:
        self.detect("claude")
        result = self.run_cli("install", "claude", "--yes", "--channel", "main", "--json")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertEqual(payload["version"], "1.5.1")


class LinkingTest(InstallerTestCase):
    def test_install_links_the_detected_hosts(self) -> None:
        self.detect("claude", "codex")
        result = self.run_cli("install", "--yes")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        for target in (self.claude_target(), self.home / ".codex" / "skills" / "img2threejs"):
            self.assertTrue(target.is_symlink(), f"{target} should be a symlink")
            self.assertEqual(Path(os.path.realpath(target)), Path(os.path.realpath(self.canonical)))

    def test_yes_never_widens_beyond_the_detected_set(self) -> None:
        self.detect("claude")
        result = self.run_cli("install", "--yes")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue(self.claude_target().is_symlink())
        self.assertFalse((self.home / ".codex" / "skills" / "img2threejs").exists())
        self.assertFalse((self.home / ".config" / "opencode" / "skills" / "img2threejs").exists())

    def test_yes_with_no_detected_host_refuses_instead_of_reporting_success(self) -> None:
        result = self.run_cli("install", "--yes")

        self.assertNotEqual(result.returncode, EXIT_OK)
        self.assertEqual(result.returncode, EXIT_REFUSED)

    def test_reinstall_is_idempotent(self) -> None:
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)
        before = os.path.realpath(self.claude_target())

        second = self.run_cli("install", "claude", "--yes", "--json")
        self.assertEqual(second.returncode, EXIT_OK, second.stderr)
        payload = json.loads(second.stdout[second.stdout.index("{"):])
        self.assertEqual(payload["targets"][0]["outcome"], "already linked")
        self.assertEqual(os.path.realpath(self.claude_target()), before)

    def test_dir_targets_a_host_the_cli_does_not_know(self) -> None:
        other = self.home / "some-other-agent" / "skills"
        other.mkdir(parents=True)
        result = self.run_cli("install", "--dir", str(other), "--yes")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue((other / "img2threejs").is_symlink())


class NonInteractiveTest(InstallerTestCase):
    def test_closed_stdin_exits_needs_input_and_installs_nothing(self) -> None:
        """readline's answer callback never fires on EOF, so the naive CLI exits 0 having done nothing."""
        self.detect("claude")
        result = self.run_cli("install", stdin="")

        self.assertEqual(result.returncode, EXIT_NEEDS_INPUT)
        self.assertNotEqual(result.returncode, EXIT_OK)
        self.assertFalse(self.claude_target().exists())
        self.assertFalse(self.canonical.exists())

    def test_unknown_host_is_an_error_not_an_empty_selection(self) -> None:
        result = self.run_cli("install", "cursor")

        self.assertEqual(result.returncode, EXIT_REFUSED)
        self.assertFalse(self.canonical.exists())


class PreExistingTargetTest(InstallerTestCase):
    def test_a_foreign_directory_is_refused_and_left_intact(self) -> None:
        target = self.claude_target()
        target.mkdir(parents=True)
        (target / "precious.txt").write_text("do not delete\n", encoding="utf-8")
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--json")

        self.assertNotEqual(result.returncode, EXIT_OK)
        self.assertTrue((target / "precious.txt").exists(), "user data must survive a refusal")
        self.assertFalse(target.is_symlink())

    def test_force_backs_up_outside_the_host_skills_directory(self) -> None:
        target = self.claude_target()
        target.mkdir(parents=True)
        (target / "precious.txt").write_text("keep me\n", encoding="utf-8")
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--force")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)

        # Exactly one entry, or the host sees two directories both declaring name: img2threejs.
        entries = sorted(p.name for p in target.parent.iterdir() if p.name.startswith("img2threejs"))
        self.assertEqual(entries, ["img2threejs"])
        self.assertTrue(target.is_symlink())

        backups = list((self.state_home / "backups").glob("claude-*/precious.txt"))
        self.assertEqual(len(backups), 1, "the displaced tree belongs under the state home")

    def test_a_symlink_to_a_directory_is_not_classified_as_a_directory(self) -> None:
        """lstat vs stat: stat follows the link and would route this to the refuse path."""
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        target = self.claude_target()
        target.parent.mkdir(parents=True)
        target.symlink_to(elsewhere)
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--dry-run", "--json")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertEqual(payload["plan"][0]["state"], "divergent")

    def test_a_dangling_symlink_is_reported_as_its_own_state(self) -> None:
        target = self.claude_target()
        target.parent.mkdir(parents=True)
        target.symlink_to(self.tmp / "gone")
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--dry-run", "--json")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertEqual(payload["plan"][0]["state"], "dangling")

    def test_a_regular_file_at_the_target_is_refused_and_not_deleted(self) -> None:
        target = self.claude_target()
        target.parent.mkdir(parents=True)
        target.write_text("not a skill\n", encoding="utf-8")
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--force")

        self.assertNotEqual(result.returncode, EXIT_OK)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), "not a skill\n")


class AdoptionTest(InstallerTestCase):
    def test_a_clean_clone_at_the_target_is_promoted_not_refused(self) -> None:
        """The old README told everyone to clone into the host directory, so this is the common case."""
        target = self.claude_target()
        self.clone_into(target)
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue(target.is_symlink())
        self.assertEqual(Path(os.path.realpath(target)), Path(os.path.realpath(self.canonical)))

    def test_untracked_work_survives_promotion(self) -> None:
        target = self.claude_target()
        self.clone_into(target)
        (target / "untracked_source.py").write_text("# exists in no other tree\n", encoding="utf-8")
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue((self.canonical / "untracked_source.py").exists())

    def test_unpushed_commits_block_adoption(self) -> None:
        target = self.claude_target()
        self.clone_into(target)
        (target / "local_only.txt").write_text("unpushed\n", encoding="utf-8")
        git(["add", "-A"], target)
        git(["commit", "-qm", "local only"], target)
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--dry-run", "--json")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertFalse(payload["plan"][0]["adoptable"])
        self.assertNotIn("promote", payload)

    def test_tracked_modifications_block_adoption(self) -> None:
        target = self.claude_target()
        self.clone_into(target)
        (target / "SKILL.md").write_text("---\nname: img2threejs\nversion: 9.9.9\n---\n", encoding="utf-8")
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", "--dry-run", "--json")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertFalse(payload["plan"][0]["adoptable"])


class UpdateTest(InstallerTestCase):
    def test_update_succeeds_from_the_detached_head_install_leaves_behind(self) -> None:
        """A resolved tag means detached HEAD, where `git pull` fails outright."""
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)

        result = self.run_cli("update", "--channel", "main", "--json")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertEqual(payload["steps"][-1]["from"], "1.4.3")
        self.assertEqual(payload["version"], "1.5.1")

    def test_update_without_an_install_is_an_error(self) -> None:
        result = self.run_cli("update")

        self.assertEqual(result.returncode, EXIT_FAIL)

    def test_update_refuses_a_checkout_with_modified_tracked_files(self) -> None:
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)
        (self.canonical / "SKILL.md").write_text("---\nversion: 0.0.0\n---\n", encoding="utf-8")

        result = self.run_cli("update")

        self.assertEqual(result.returncode, EXIT_REFUSED)
        # Nothing was stashed, reset, or discarded.
        self.assertIn("0.0.0", (self.canonical / "SKILL.md").read_text(encoding="utf-8"))

    def test_untracked_files_alone_do_not_block_an_update(self) -> None:
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)
        (self.canonical / "scratch.json").write_text("{}\n", encoding="utf-8")

        result = self.run_cli("update", "--channel", "main")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue((self.canonical / "scratch.json").exists())


class UninstallTest(InstallerTestCase):
    def test_uninstall_removes_the_link_and_keeps_the_checkout(self) -> None:
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)

        result = self.run_cli("uninstall", "claude")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertFalse(self.claude_target().exists())
        self.assertTrue(self.canonical.exists())

    def test_uninstall_recovers_a_dir_target_from_the_receipt(self) -> None:
        """realpath matching alone cannot find a --dir link; the receipt can."""
        other = self.home / "some-other-agent" / "skills"
        other.mkdir(parents=True)
        self.assertEqual(self.run_cli("install", "--dir", str(other), "--yes").returncode, EXIT_OK)

        result = self.run_cli("uninstall")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertFalse((other / "img2threejs").exists())

    def test_uninstall_leaves_a_link_pointing_somewhere_else(self) -> None:
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)

        elsewhere = self.tmp / "someones-fork"
        elsewhere.mkdir()
        target = self.claude_target()
        target.unlink()
        target.symlink_to(elsewhere)

        result = self.run_cli("uninstall", "claude")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue(target.is_symlink(), "a hand-made link to a fork must survive")
        self.assertEqual(Path(os.path.realpath(target)), Path(os.path.realpath(elsewhere)))

    def test_uninstall_refuses_a_target_that_became_a_directory(self) -> None:
        self.detect("claude")
        self.assertEqual(self.run_cli("install", "claude", "--yes").returncode, EXIT_OK)
        target = self.claude_target()
        target.unlink()
        target.mkdir()
        (target / "precious.txt").write_text("keep\n", encoding="utf-8")

        result = self.run_cli("uninstall", "claude")

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue((target / "precious.txt").exists())


class SafetyTest(InstallerTestCase):
    def test_a_link_failure_never_degrades_to_a_copy(self) -> None:
        self.detect("claude")
        result = self.run_cli("install", "claude", "--yes", IMG2THREEJS_FORCE_LINK_FAILURE="1")

        self.assertNotEqual(result.returncode, EXIT_OK)
        target = self.claude_target()
        self.assertFalse(target.is_dir() and not target.is_symlink(), "a copy is the drift this ends")

    def test_a_held_lock_stops_a_second_run(self) -> None:
        self.state_home.mkdir(parents=True)
        (self.state_home / ".lock").write_text(
            json.dumps({"pid": 1, "hostname": "other", "at": "2026-01-01T00:00:00Z"}), encoding="utf-8"
        )
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes")

        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertFalse(self.canonical.exists())

    def test_an_incomplete_checkout_links_nothing(self) -> None:
        empty = self.tmp / "empty-origin"
        empty.mkdir()
        git(["init", "-q", "."], empty)
        (empty / "README.md").write_text("no skill here\n", encoding="utf-8")
        git(["add", "-A"], empty)
        git(["commit", "-qm", "empty"], empty)
        git(["tag", "-a", "v1.0.0", "-m", "v1.0.0"], empty)
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes", IMG2THREEJS_REPO_URL=f"file://{empty}")

        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertFalse(self.claude_target().exists(), "no host may be linked to an incomplete checkout")

    def test_a_foreign_checkout_at_the_canonical_path_is_refused(self) -> None:
        other = self.tmp / "other-project"
        other.mkdir()
        git(["init", "-q", "."], other)
        (other / "SKILL.md").write_text("---\nversion: 1.0.0\n---\n", encoding="utf-8")
        git(["add", "-A"], other)
        git(["commit", "-qm", "other"], other)
        self.canonical.parent.mkdir(parents=True, exist_ok=True)
        git(["clone", "-q", str(other), str(self.canonical)], self.tmp)
        self.detect("claude")

        result = self.run_cli("install", "claude", "--yes")

        self.assertEqual(result.returncode, EXIT_REFUSED)

    def test_local_scope_outside_a_project_is_refused(self) -> None:
        self.detect("claude")
        outside = self.tmp / "no-project"
        outside.mkdir()
        result = subprocess.run(
            ["node", str(CLI), "install", "claude", "--local", "--yes"],
            cwd=outside,
            capture_output=True,
            text=True,
            env=self.env(),
        )

        self.assertEqual(result.returncode, EXIT_REFUSED)

    def test_local_scope_refuses_an_unignored_target(self) -> None:
        """git stores the link's literal absolute target, so a committed link resolves nowhere else."""
        self.detect("claude")
        project = self.tmp / "project"
        project.mkdir()
        git(["init", "-q", "."], project)

        result = subprocess.run(
            ["node", str(CLI), "install", "claude", "--local", "--yes"],
            cwd=project,
            capture_output=True,
            text=True,
            env=self.env(),
        )

        self.assertEqual(result.returncode, EXIT_REFUSED)
        self.assertFalse((project / ".claude" / "skills" / "img2threejs").exists())

    def test_local_scope_accepts_an_ignored_target(self) -> None:
        self.detect("claude")
        project = self.tmp / "project-ignored"
        project.mkdir()
        git(["init", "-q", "."], project)
        (project / ".gitignore").write_text(".claude/skills/img2threejs\n", encoding="utf-8")

        result = subprocess.run(
            ["node", str(CLI), "install", "claude", "--local", "--yes"],
            cwd=project,
            capture_output=True,
            text=True,
            env=self.env(),
        )

        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertTrue((project / ".claude" / "skills" / "img2threejs").is_symlink())


class HermeticityTest(InstallerTestCase):
    def test_the_cli_resolves_home_through_os_homedir_only(self) -> None:
        """os.homedir() honours $HOME; os.userInfo().homedir does not, and using it would make
        every test above operate on the developer's real skills directories."""
        source = CLI.read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))
        self.assertNotIn("userInfo(", code)

    def test_zzz_real_home_untouched(self) -> None:
        self.assertEqual(_real_entrypoint_state(), self.baseline_real_state)


if __name__ == "__main__":
    unittest.main()
