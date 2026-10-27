"""Release safety: reject wrong tags and refuse changes to published artifacts."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("release", SCRIPTS / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
sys.modules["release"] = release
spec = importlib.util.spec_from_file_location("publish_release", SCRIPTS / "publish_release.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


@pytest.mark.parametrize("tag", ["v9.9.9", "0.1.0", "v0.1.0-rc1", "v0.1.0;echo bad"])
def test_release_refuses_mismatched_or_unsupported_tag(tag):
    with pytest.raises(ValueError, match="must equal"):
        release.check_tag(tag)


def setup_publisher(monkeypatch, tmp_path, *, draft=False, immutable=True,
                    enabled=True, remote_sha="a" * 40, existing_bytes=b"tested"):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "wheel.whl").write_bytes(b"tested")
    calls = []
    monkeypatch.setattr(publisher, "verify", lambda *args: None)
    def fake_gh(*args):
        calls.append(args)
        if args[0] == "api":
            if args[1].endswith("immutable-releases"):
                return json.dumps({"enabled": enabled})
            if "/commits/" in args[1]:
                return json.dumps({"sha": remote_sha})
        if args[:2] == ("release", "download"):
            (Path(args[args.index("--dir") + 1]) / "wheel.whl").write_bytes(existing_bytes)
        else:
            raise AssertionError(f"Unexpected GitHub mutation: {args}")
        return ""
    monkeypatch.setattr(publisher, "gh", fake_gh)
    monkeypatch.setattr(publisher.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps({"draft": draft, "immutable": immutable,
                                       "assets": [{"name": "wheel.whl"}]})))
    return dist, calls


def test_published_matching_release_is_noop(monkeypatch, tmp_path):
    dist, calls = setup_publisher(monkeypatch, tmp_path)
    publisher.publish(dist, "v0.1.0", "a" * 40)
    assert all(call[0] == "api" or call[:2] == ("release", "download") for call in calls)


@pytest.mark.parametrize("options,message", [
    ({"enabled": False}, "Enable release immutability"),
    ({"remote_sha": "b" * 40}, "no longer points"),
    ({"existing_bytes": b"different"}, "differs"),
    ({"draft": True, "existing_bytes": b"different"}, "differs"),
    ({"immutable": False}, "incomplete or mutable"),
])
def test_release_stops_before_mutation(monkeypatch, tmp_path, options, message):
    dist, _ = setup_publisher(monkeypatch, tmp_path, **options)
    with pytest.raises(ValueError, match=message):
        publisher.publish(dist, "v0.1.0", "a" * 40, finalize=True)


def test_ci_stages_draft_without_admin_api_or_publication(monkeypatch, tmp_path):
    dist, calls = setup_publisher(monkeypatch, tmp_path, draft=True)
    publisher.publish(dist, "v0.1.0", "a" * 40)
    assert not any(call[0] == "api" and call[1].endswith("immutable-releases") for call in calls)
    assert not any(call[:2] == ("release", "edit") for call in calls)


def test_changed_artifact_fails_checksum_verification(monkeypatch, tmp_path):
    (tmp_path / "wheel.whl").write_bytes(b"changed after testing")
    (tmp_path / "release-manifest.json").write_text(json.dumps({
        "version": release.version(), "source_revision": "a" * 40, "tag": "v0.1.0",
        "artifacts": {"wheel.whl": {"sha256": "0" * 64, "size": 21}}}))
    with pytest.raises(AssertionError, match="wheel.whl"):
        release.verify(tmp_path, "a" * 40, "v0.1.0")
