"""Release automation tests; no real git writes, tags or GitHub calls."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import release


def repository(root, version="1.0.0"):
    component = root / release.COMPONENT
    component.mkdir(parents=True)
    (component / "manifest.json").write_text(json.dumps({"version": version}))
    (component / "__init__.py").write_text('"""Example."""\n')
    for name in ("README.md", "LICENSE", "hacs.json"):
        (root / name).write_text("{}")
    return component


def pull(number=1, sha="merge1", merged="2026-11-16T00:00:00Z", base="main"):
    return {
        "number": number, "merge_commit_sha": sha, "merged_at": merged,
        "base": {"ref": base}, "title": f"Feature {number}",
        "body": "## Summary\nSummary\n## Changelog\n- Added feature\n## Tests\nTests",
        "html_url": f"https://github.com/example/repo/pull/{number}",
    }


class ReleaseHelperTests(unittest.TestCase):
    def test_first_version_and_manual_bump(self):
        self.assertEqual(release.next_version("1.0.0", []), "1.0.0")
        self.assertEqual(release.next_version("1.1.0", ["v1.0.0"]), "1.1.0")

    def test_automatic_patch_increment(self):
        self.assertEqual(release.next_version("1.0.0", ["v1.0.0"]), "1.0.1")
        self.assertEqual(release.next_version("1.0.0", ["v1.2.3"]), "1.2.4")
        self.assertEqual(release.next_version("1.0.0", ["other", "v1.0.1-rc1"]), "1.0.0")

    def test_invalid_versions(self):
        for value in ("1.0", "v1.0.0", "01.0.0", "../1.0.0", "1.0.0;echo bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.version_tuple(value)

    def test_archive_only_contains_installation_and_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = repository(root)
            (component / "__pycache__").mkdir()
            (component / "__pycache__/module.pyc").write_bytes(b"cache")
            (component / ".env").write_text("SECRET")
            (component / "credentials.json").write_text("SECRET")
            (component / "translations").mkdir()
            (component / "translations/de.json").write_text("{}")
            archive = release.build_archive(root, "1.0.0")
            with ZipFile(archive) as data:
                names = data.namelist()
                self.assertIn("custom_components/remotepower/manifest.json", names)
                self.assertIn("custom_components/remotepower/translations/de.json", names)
                self.assertIn("README.md", names)
                self.assertFalse(any("credentials" in name or ".env" in name
                                     or "__pycache__" in name for name in names))
                self.assertIsNone(data.testzip())

    def test_archive_requires_matching_manifest_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository(root)
            with self.assertRaises(ValueError):
                release.build_archive(root, "1.0.1")

    def test_changelog_section_and_fallback(self):
        self.assertEqual(release.changelog_section(pull()["body"]), "- Added feature")
        self.assertEqual(release.changelog_section("## Änderungen\n- Neu\n"), "- Neu")
        self.assertEqual(release.changelog_section("No section"), "No section")

    def test_release_notes_render_pr_text_only(self):
        text = "$(echo malicious); `not a command`"
        notes = release.format_release_notes([{
            "number": 1, "title": "Title", "url": "https://example.test",
            "body": f"## Changelog\n{text}\n## Tests\nignored",
        }], "1.0.0")
        self.assertIn(text, notes)
        self.assertNotIn("ignored", notes)
        self.assertIn("# RemotePower for Home Assistant 1.0.0", notes)

    def test_no_pr_notes_fallback(self):
        self.assertIn("Maintenance release", release.format_release_notes([], "1.0.0"))

    def test_first_release_includes_earlier_merged_pr(self):
        def run(*args):
            if args[0] == "git":
                return "direct\nmerge1\nbootstrap"
            commit = args[-1].split("/commits/")[1].split("/")[0]
            return json.dumps([pull()] if commit == "merge1" else [])
        with patch.object(release, "run", side_effect=run):
            result = release.collect_release_pulls("HEAD")
        self.assertEqual([item["number"] for item in result], [1])

    def test_incremental_notes_use_previous_tag_range(self):
        with patch.object(release, "run", side_effect=[
            "merge2", json.dumps([pull(2, "merge2")]),
        ]) as run:
            result = release.collect_release_pulls("HEAD", "v1.0.0")
        self.assertEqual(run.call_args_list[0].args, (
            "git", "rev-list", "--first-parent", "v1.0.0..HEAD",
        ))
        self.assertEqual(result[0]["number"], 2)

    def test_manual_latest_pr_looks_beyond_previous_release(self):
        with patch.object(release, "run", side_effect=[
            "direct\nmerge2\nmerge1", "[]", json.dumps([pull(2, "merge2")]),
        ]) as run:
            result = release.collect_release_pulls("HEAD", "v1.0.0", latest_only=True)
        self.assertEqual(run.call_args_list[0].args[-1], "HEAD")
        self.assertEqual(result[0]["number"], 2)
        self.assertEqual(run.call_count, 3)

    def test_unmerged_wrong_base_and_unrelated_prs_excluded(self):
        with patch.object(release, "run", side_effect=[
            "merge1", json.dumps([
                pull(1, merged=None), pull(2, base="other"), pull(3, sha="unreachable"),
            ]),
        ]):
            self.assertEqual(release.collect_release_pulls("HEAD"), [])

    def test_release_lookup_failure_is_not_treated_as_missing(self):
        result = subprocess.CompletedProcess([], 1, "", "authentication failed")
        with patch.object(release.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Cannot inspect"):
                release.optional_release()

    def test_missing_release_is_expected(self):
        result = subprocess.CompletedProcess([], 1, "", "release not found")
        with patch.object(release.subprocess, "run", return_value=result):
            self.assertIsNone(release.optional_release())


class ReleaseMainTests(unittest.TestCase):
    def exercise(self, *, tags="", tag_head="OLD", existing=False, latest=False,
                 remote="HEAD", dirty=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        repository(root)
        state = {"committed": False}

        def run(*args):
            if args == ("git", "branch", "--show-current"):
                return "main"
            if args == ("git", "status", "--porcelain"):
                return " M README.md" if dirty else ""
            if args == ("git", "rev-parse", "HEAD"):
                return "BUMPED" if state["committed"] else "HEAD"
            if args == ("git", "tag", "--list"):
                return tags
            if args[:3] == ("git", "rev-list", "-n"):
                return tag_head
            if args[:2] == ("git", "commit"):
                state["committed"] = True
            if args[:2] == ("git", "ls-remote"):
                sha = "BUMPED" if state["committed"] and remote == "HEAD" else remote
                return f"{sha}\trefs/heads/main"
            return ""

        lookup = {"tagName": "v1.0.0"} if existing else None
        with (
            patch.object(release, "ROOT", root),
            patch.object(release, "run", side_effect=run) as mocked,
            patch.object(release, "collect_release_pulls", return_value=[]) as collect,
            patch.object(release, "optional_release", return_value=lookup),
            patch.dict(release.os.environ, {"USE_LATEST_PR": "true" if latest else "false"}),
            patch("builtins.print"),
        ):
            try:
                release.main()
            except RuntimeError as err:
                return root, mocked, collect, err
        return root, mocked, collect, None

    def test_initial_release_keeps_1_0_0_and_creates_tag(self):
        root, run, _, error = self.exercise()
        self.assertIsNone(error)
        calls = [call.args for call in run.call_args_list]
        self.assertTrue(any(args[:3] == ("git", "tag", "-a") and args[3] == "v1.0.0"
                            for args in calls))
        self.assertTrue(any(args[:3] == ("gh", "release", "create") for args in calls))
        self.assertEqual(json.loads((root / release.MANIFEST).read_text())["version"], "1.0.0")

    def test_rerun_uploads_without_bump_or_tag_overwrite(self):
        root, run, _, error = self.exercise(tags="v1.0.0", tag_head="HEAD", existing=True)
        self.assertIsNone(error)
        calls = [call.args for call in run.call_args_list]
        self.assertFalse(any(args[:3] == ("git", "tag", "-a") for args in calls))
        self.assertFalse(any(args[:3] == ("gh", "release", "edit") for args in calls))
        self.assertTrue(any(args[:3] == ("gh", "release", "upload") for args in calls))
        self.assertEqual(json.loads((root / release.MANIFEST).read_text())["version"], "1.0.0")

    def test_new_commit_advances_patch_and_pushes_manifest(self):
        root, run, _, error = self.exercise(tags="v1.0.0")
        self.assertIsNone(error)
        calls = [call.args for call in run.call_args_list]
        self.assertIn(("git", "push", "origin", "HEAD:main"), calls)
        self.assertEqual(json.loads((root / release.MANIFEST).read_text())["version"], "1.0.1")
        self.assertFalse(any("--force" in args for args in calls))

    def test_manual_latest_replaces_notes_on_existing_release(self):
        _, run, collect, error = self.exercise(
            tags="v1.0.0", tag_head="HEAD", existing=True, latest=True,
        )
        self.assertIsNone(error)
        self.assertTrue(collect.call_args.kwargs["latest_only"])
        self.assertTrue(any(call.args[:3] == ("gh", "release", "edit")
                            for call in run.call_args_list))

    def test_concurrent_main_update_blocks_publishing(self):
        _, run, _, error = self.exercise(remote="OTHER")
        self.assertIsNotNone(error)
        self.assertFalse(any(call.args[:3] in (
            ("git", "tag", "-a"), ("gh", "release", "create"),
        ) for call in run.call_args_list))

    def test_dirty_checkout_blocks_publishing(self):
        _, run, _, error = self.exercise(dirty=True)
        self.assertIsNotNone(error)
        self.assertEqual(run.call_count, 2)
