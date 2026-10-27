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
        "version": release.version(), "source_revision": "a" * 40, "tag": f"v{release.version()}",
        "artifacts": {"wheel.whl": {"sha256": "0" * 64, "size": 21}}}))
    with pytest.raises(AssertionError, match="wheel.whl"):
        release.verify(tmp_path, "a" * 40, f"v{release.version()}")


@pytest.mark.parametrize("already_created", [False, True])
def test_draft_lookup_stages_and_resumes_without_duplicate_creation(monkeypatch, tmp_path, already_created):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "wheel.whl").write_bytes(b"tested")
    monkeypatch.setattr(publisher, "verify", lambda *args: None)
    monkeypatch.setattr(publisher.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout=json.dumps({"status": "404"}), stderr="Not Found"))
    created = already_created
    calls = []
    def fake_gh(*args):
        nonlocal created
        calls.append(args)
        if args[0] == "api" and "/commits/" in args[1]:
            return json.dumps({"sha": "a" * 40})
        if args[:4] == ("api", "--paginate", "--slurp", f"repos/{publisher.REPOSITORY}/releases?per_page=100"):
            # Include another tag on the first page to exercise pagination/filtering.
            return json.dumps([[{"tag_name": "v0.0.1"}],
                               [{"id": 42, "tag_name": "v0.2.1", "draft": True, "assets": []}] if created else []])
        if args[:2] == ("release", "create"):
            assert not created
            created = True
            return ""
        if args[:2] == ("release", "upload"):
            assert Path(args[3]).read_bytes() == b"tested"
            return ""
        raise AssertionError(f"Unexpected GitHub call: {args}")
    monkeypatch.setattr(publisher, "gh", fake_gh)
    publisher.publish(dist, "v0.2.1", "a" * 40)
    assert sum(call[:2] == ("release", "create") for call in calls) == int(not already_created)
    assert sum(call[:2] == ("release", "upload") for call in calls) == 1
    assert not any(call[:2] == ("release", "edit") for call in calls)


def test_final_publication_verifies_release_by_id(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(publisher, "verify", lambda *args: None)
    draft = {"id": 42, "draft": True, "assets": []}
    monkeypatch.setattr(publisher, "find_release", lambda tag: draft)
    calls = []
    def fake_gh(*args):
        calls.append(args)
        if args == ("api", f"repos/{publisher.REPOSITORY}/immutable-releases"):
            return json.dumps({"enabled": True})
        if args == ("api", f"repos/{publisher.REPOSITORY}/commits/v0.2.1"):
            return json.dumps({"sha": "a" * 40})
        if args == ("api", f"repos/{publisher.REPOSITORY}/releases/42"):
            return json.dumps({"immutable": True, "html_url": "https://example.test/release"})
        assert args[:2] == ("release", "edit")
        return ""
    monkeypatch.setattr(publisher, "gh", fake_gh)
    publisher.publish(dist, "v0.2.1", "a" * 40, finalize=True)
    assert calls[-1] == ("api", f"repos/{publisher.REPOSITORY}/releases/42")


def test_draft_visibility_delay_retries_reads_without_creating_twice(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(publisher, "verify", lambda *args: None)
    replies = iter([None,None,None,{"id":42,"draft":True,"assets":[]}])
    monkeypatch.setattr(publisher, "find_release", lambda tag: next(replies))
    delays, calls = [], []
    monkeypatch.setattr(publisher.time, "sleep", delays.append)
    def fake_gh(*args):
        calls.append(args)
        if args[0] == "api" and "/commits/" in args[1]:
            return json.dumps({"sha":"a"*40})
        assert args[:2] == ("release","create")
        return ""
    monkeypatch.setattr(publisher,"gh",fake_gh)
    publisher.publish(dist,"v0.3.0","a"*40)
    assert delays == [2,2]
    assert sum(call[:2] == ("release","create") for call in calls) == 1
