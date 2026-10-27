"""Publish tested assets without replacing tags or existing assets (GitHub CLI auth)."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from release import digest, verify

REPOSITORY = "PredictabilityAtScale/anomaly-detection"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def publish(dist, tag, revision, *, finalize=False):
    verify(dist, revision, tag)
    # This endpoint requires admin-read, unavailable to GITHUB_TOKEN. Only the
    # owner's explicit final publication uses it; CI stages a verified draft.
    if finalize:
        settings = json.loads(gh("api", f"repos/{REPOSITORY}/immutable-releases"))
        if not settings["enabled"]:
            raise ValueError("Enable release immutability in repository Settings > General > Releases first")
    remote_sha = json.loads(gh("api", f"repos/{REPOSITORY}/commits/{tag}"))["sha"]
    if remote_sha != revision:
        raise ValueError("Remote tag no longer points to the tested source revision")
    endpoint = f"repos/{REPOSITORY}/releases/tags/{tag}"
    found = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if found.returncode:
        error = json.loads(found.stdout)
        if str(error.get("status")) != "404":
            raise RuntimeError(found.stderr)
        with tempfile.TemporaryDirectory() as temp:
            notes = Path(temp) / "notes.md"
            feature_path = Path(__file__).resolve().parents[1] / "docs/releases" / f"{tag[1:]}.md"
            feature_notes = feature_path.read_text(encoding="utf-8") + "\n\n" if feature_path.is_file() else ""
            notes.write_text(
                feature_notes +
                f"Anomalyzer {tag[1:]} — local Python analysis library.\n\n"
                f"Source revision: `{revision}`.\n\n"
                "Wheel and source distribution tested on Python 3.11–3.13; "
                "Linux/Python 3.12 Lambda consumer verified offline. "
                "See SHA256SUMS and release-manifest.json for artifact identities.\n\n"
                f"[Release and consumption guide](https://github.com/{REPOSITORY}/blob/{tag}/docs/releases/README.md).\n",
                encoding="utf-8")
            gh("release", "create", tag, "--repo", REPOSITORY, "--draft", "--verify-tag",
               "--target", revision, "--title", f"Anomalyzer {tag}", "--notes-file", str(notes))
        release = json.loads(gh("api", endpoint))
    else:
        release = json.loads(found.stdout)
    expected = {p.name: p for p in dist.iterdir() if p.is_file() and p.name != ".gitignore"}
    existing = {item["name"] for item in release["assets"]}
    if not existing <= set(expected):
        raise ValueError("Release contains unexpected assets; refusing to change it")
    with tempfile.TemporaryDirectory() as temp:
        for name in sorted(existing):
            gh("release", "download", tag, "--repo", REPOSITORY,
               "--pattern", name, "--dir", temp)
            if digest(Path(temp) / name) != digest(expected[name]):
                raise ValueError(f"Existing asset {name} differs; refusing overwrite")
    if not release["draft"]:
        if existing != set(expected) or not release.get("immutable"):
            raise ValueError("Published release is incomplete or mutable; create a new version")
        print("Published immutable release already matches; nothing changed")
        return
    for name in sorted(set(expected) - existing):
        gh("release", "upload", tag, str(expected[name]), "--repo", REPOSITORY)
    if not finalize:
        print(f"Verified draft staged for {tag}; owner must run this command with --publish to seal it")
        return
    gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false")
    sealed = json.loads(gh("api", endpoint))
    if not sealed.get("immutable"):
        raise RuntimeError("GitHub did not report an immutable release; investigate repository settings")
    print(sealed["html_url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--publish", action="store_true",
                        help="Owner-only final step: require immutability, then publish the draft")
    args = parser.parse_args()
    publish(args.dist, args.tag, args.revision, finalize=args.publish)
