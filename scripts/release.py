"""Validate distributions and create/check an inventory bound to a source revision."""
from __future__ import annotations

import argparse
import ast
import configparser
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def version():
    tree = ast.parse((ROOT / "src/anomalyzer/_version.py").read_text())
    return next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__"
                        for target in node.targets))


def check_tag(tag):
    expected = f"v{version()}"
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or tag != expected:
        raise ValueError(f"tag {tag!r} must equal {expected!r}; stable X.Y.Z releases only")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_archives(dist):
    ver = version()
    wheel = dist / f"anomalyzer-{ver}-py3-none-any.whl"
    sdist = dist / f"anomalyzer-{ver}.tar.gz"
    assert sorted(dist.glob("*.whl")) == [wheel]
    assert sorted(dist.glob("*.tar.gz")) == [sdist]
    expected_modules = {p.relative_to(ROOT / "src").as_posix()
                        for p in (ROOT / "src/anomalyzer").rglob("*.py")}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "anomalyzer/py.typed" in names
        assert expected_modules <= set(names), "wheel missing source modules"
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        meta = BytesParser().parsebytes(archive.read(f"anomalyzer-{ver}.dist-info/METADATA"))
        assert meta["Name"] == "anomalyzer" and meta["Version"] == ver
        assert set(meta["Requires-Python"].split(",")) == {">=3.11", "<3.14"}
        assert meta["License-Expression"] == "MIT"
        assert archive.read(f"anomalyzer-{ver}.dist-info/licenses/LICENSE") == (ROOT / "LICENSE").read_bytes()
        entry = configparser.ConfigParser()
        entry.read_string(archive.read(f"anomalyzer-{ver}.dist-info/entry_points.txt").decode())
        assert dict(entry["console_scripts"]) == {
            "anomalyzer": "anomalyzer.cli:main", "anomalyzer-mcp": "anomalyzer.mcp:main"}
    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
        prefix = f"anomalyzer-{ver}/"
        assert {prefix + "src/" + name for name in expected_modules} <= names
        for path in ("pyproject.toml", "LICENSE", "README.md", "uv.lock",
                     "examples/library/guard_smoke.py", "scripts/verify_distribution.py"):
            assert prefix + path in names, path
        metadata = BytesParser().parsebytes(archive.extractfile(prefix + "PKG-INFO").read())
        assert metadata["Version"] == ver and metadata["Name"] == "anomalyzer"
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = next(p for p in lock["package"] if p["name"] == "anomalyzer")
    # uv omits the root version when metadata declares it dynamic.
    assert locked.get("version", ver) == ver
    return wheel, sdist


def create(dist, revision, tag):
    if tag:
        check_tag(tag)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full Git commit SHA")
    wheel, _ = check_archives(dist)
    runtime = dist / "runtime-dependencies.txt"
    assert runtime.is_file(), "export locked runtime dependencies first"
    base = runtime.read_text(encoding="utf-8")
    # Offline lock resolves the local wheelhouse; online lock pins the exact release asset.
    suffix = f" --hash=sha256:{digest(wheel)}\n"
    (dist / "requirements-offline.txt").write_text(
        base + f"\nanomalyzer=={version()}" + suffix, encoding="utf-8")
    url = ("https://github.com/PredictabilityAtScale/anomaly-detection/releases/download/"
           f"v{version()}/{wheel.name}")
    (dist / "requirements-guard-py312-linux-x86_64.txt").write_text(
        base + f"\nanomalyzer @ {url}" + suffix, encoding="utf-8")
    assets = sorted(p for p in dist.iterdir() if p.is_file()
                    and p.name not in {".gitignore", "release-manifest.json", "SHA256SUMS"})
    manifest = {"version": version(), "tag": tag or None, "source_revision": revision,
                "artifacts": {p.name: {"sha256": digest(p), "size": p.stat().st_size}
                              for p in assets}}
    manifest_path = dist / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (dist / "SHA256SUMS").write_text(
        "".join(f"{digest(p)}  {p.name}\n" for p in sorted(assets + [manifest_path])),
        encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def verify(dist, revision=None, tag=None):
    manifest = json.loads((dist / "release-manifest.json").read_text())
    if revision:
        assert manifest["source_revision"] == revision
    if tag:
        check_tag(tag)
        assert manifest["tag"] == tag
    assert manifest["version"] == version()
    for name, entry in manifest["artifacts"].items():
        assert Path(name).name == name
        assert digest(dist / name) == entry["sha256"], name
        assert (dist / name).stat().st_size == entry["size"], name
    checksum_files = set()
    for line in (dist / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split("  ", 1)
        assert Path(name).name == name
        assert digest(dist / name) == sha, name
        checksum_files.add(name)
    assert checksum_files == set(manifest["artifacts"]) | {"release-manifest.json"}
    assert {p.name for p in dist.iterdir() if p.is_file() and p.name != ".gitignore"} == checksum_files | {"SHA256SUMS"}
    check_archives(dist)
    print("Release inventory and checksums verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check-version", "create", "verify"])
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--revision")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if args.command == "check-version":
        check_tag(args.tag)
        print(version())
    elif args.command == "create":
        create(args.dist, args.revision or "", args.tag)
    else:
        verify(args.dist, args.revision, args.tag)
