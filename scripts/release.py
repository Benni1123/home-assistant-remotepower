"""Publish validated main; treat PR text as Markdown data, never shell code."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = Path("custom_components/remotepower")
MANIFEST = COMPONENT / "manifest.json"


def version_tuple(version: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError(f"Invalid stable version: {version}")
    return tuple(int(part) for part in version.split("."))


def next_version(current: str, tags: list[str]) -> str:
    """Use a higher manifest version; otherwise advance the highest stable patch."""
    current_parts = version_tuple(current)
    versions = [
        version_tuple(tag.removeprefix("v"))
        for tag in tags
        if re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag)
    ]
    if not versions or current_parts > max(versions):
        return current
    major, minor, patch = max(current_parts, *versions)
    return f"{major}.{minor}.{patch + 1}"


def _installation_file(relative: Path) -> bool:
    """Exclude arbitrary credentials, caches and untracked deployment files."""
    if len(relative.parts) == 1:
        return relative.suffix == ".py" or relative.name in (
            "manifest.json", "strings.json", "services.yaml",
        )
    if len(relative.parts) == 2 and relative.parts[0] == "translations":
        return relative.suffix == ".json"
    if len(relative.parts) == 2 and relative.parts[0] == "brand":
        return relative.name == "LICENSE" or relative.name in {
            f"{dark}{kind}{scale}.png"
            for dark in ("", "dark_")
            for kind in ("icon", "logo")
            for scale in ("", "@2x")
        }
    return False


def build_archive(root: Path, version: str) -> Path:
    version_tuple(version)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if manifest["version"] != version:
        raise ValueError("Archive version does not match manifest")
    component = root / COMPONENT
    files = [
        path for path in component.rglob("*")
        if path.is_file() and not path.is_symlink()
        and _installation_file(path.relative_to(component))
    ]
    files.extend(root / name for name in ("README.md", "LICENSE", "hacs.json"))
    if any(path.is_symlink() for path in files):
        raise ValueError("Symlinks are not allowed in release archives")
    output = root / "dist" / f"home-assistant-remotepower-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(root).as_posix())
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Release archive failed verification")
    return output


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def optional_release(tag: str | None = None) -> dict | None:
    args = ["gh", "release", "view"]
    if tag is not None:
        args.append(tag)
    result = subprocess.run(
        [*args, "--json", "tagName"], cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    if "release not found" in result.stderr.lower():
        return None
    raise RuntimeError(f"Cannot inspect GitHub release: {result.stderr}")


def changelog_section(body: str) -> str:
    match = re.search(
        r"^##[ \t]+(?:Changelog|Changes|Änderungen)[ \t]*:?[ \t]*\r?$\n?"
        r"(.*?)(?=^##[ \t]+|\Z)",
        body, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    return (match.group(1) if match else body).strip()


def collect_release_pulls(head: str, base: str | None = None, latest_only=False) -> list[dict]:
    """Walk reachable first-parent merges, including all PRs on the first release.

    For manual latest-PR mode the full history is inspected, not just the
    interval since the previous release. An unrelated or unmerged PR is excluded.
    """
    revision = head if latest_only or base is None else f"{base}..{head}"
    commits = run("git", "rev-list", "--first-parent", revision).splitlines()
    pulls = {}
    for commit in commits:
        associated = json.loads(run(
            "gh", "api",
            f"repos/{{owner}}/{{repo}}/commits/{commit}/pulls?per_page=100",
        ))
        for pull in associated:
            if (
                not pull.get("merged_at")
                or pull.get("base", {}).get("ref") != "main"
                or pull.get("merge_commit_sha") != commit
            ):
                continue
            pulls[pull["number"]] = {
                "number": pull["number"], "title": pull["title"],
                "body": pull.get("body") or "", "url": pull["html_url"],
                "mergedAt": pull["merged_at"],
            }
        if latest_only and pulls:
            break
    ordered = sorted(pulls.values(), key=lambda pull: (pull["mergedAt"], pull["number"]))
    return ordered[-1:] if latest_only else ordered


def format_release_notes(pulls: list[dict], version: str) -> str:
    lines = [f"# RemotePower for Home Assistant {version}", "", "## Changelog", ""]
    for pull in pulls:
        lines.extend([
            f"### {pull['title']} ([#{pull['number']}]({pull['url']}))", "",
            changelog_section(pull.get("body") or "") or pull["title"], "",
        ])
    if not pulls:
        lines.extend(["Maintenance release; no matching merged pull request was found.", ""])
    return "\n".join(lines)


def main() -> None:
    if run("git", "branch", "--show-current") != "main":
        raise RuntimeError("Releases must run on main")
    if run("git", "status", "--porcelain"):
        raise RuntimeError("Refusing to release a modified checkout")
    latest_only = os.environ.get("USE_LATEST_PR", "false").lower() == "true"
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    current = manifest["version"]
    version_tuple(current)
    head = run("git", "rev-parse", "HEAD")
    tags = run("git", "tag", "--list").splitlines()
    current_tag = f"v{current}"
    tag_at_head = (
        current_tag in tags and run("git", "rev-list", "-n", "1", current_tag) == head
    )
    # A rerun repairs the same tag/asset instead of incrementing a second time.
    version = current if tag_at_head else next_version(current, tags)
    previous = optional_release()
    pulls = collect_release_pulls(
        head, previous["tagName"] if previous else None, latest_only=latest_only,
    )
    if version != current:
        manifest["version"] = version
        (ROOT / MANIFEST).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    archive = build_archive(ROOT, version)
    notes = ROOT / "dist" / f"release-notes-{version}.md"
    notes.write_text(format_release_notes(pulls, version), encoding="utf-8")
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    if version != current:
        run("git", "add", str(MANIFEST))
        run("git", "commit", "-m", f"chore: release v{version}")
        run("git", "push", "origin", "HEAD:main")
        head = run("git", "rev-parse", "HEAD")
    remote_main = run("git", "ls-remote", "origin", "refs/heads/main").split()
    if not remote_main or remote_main[0] != head:
        raise RuntimeError("main changed while validating; let the next run release it")
    tag = f"v{version}"
    existing = optional_release(tag)
    if not tag_at_head:
        run("git", "tag", "-a", tag, "-m", f"RemotePower {version}")
        run("git", "push", "origin", tag)
    if existing:
        run("gh", "release", "upload", tag, str(archive), "--clobber")
        # Leave hand-edited existing notes alone unless explicitly asked to
        # replace them using the manual latest-PR checkbox.
        if latest_only:
            run("gh", "release", "edit", tag, "--notes-file", str(notes))
    else:
        run(
            "gh", "release", "create", tag, str(archive), "--verify-tag",
            "--title", f"RemotePower {version}", "--notes-file", str(notes),
        )
    print(f"Published {tag}: {archive.name}")


if __name__ == "__main__":
    main()
