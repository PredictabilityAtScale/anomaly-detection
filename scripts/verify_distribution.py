"""Install wheel AND sdist in clean environments outside the source tree (requires uv)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), cwd=cwd, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--python", default="3.12")
    args = parser.parse_args()
    dist = args.dist.resolve()
    artifacts = list(dist.glob("*.whl")) + list(dist.glob("*.tar.gz"))
    assert len(artifacts) == 2, "expected exactly one wheel and one sdist"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    # Ignore caller TEMP settings that point inside this repository.
    with tempfile.TemporaryDirectory(prefix="anomalyzer-consumer-", dir=Path.home()) as tmp:
        outside = Path(tmp).resolve()
        assert not outside.is_relative_to(ROOT)
        smoke = outside / "guard_smoke.py"
        shutil.copyfile(ROOT / "examples/library/guard_smoke.py", smoke)
        for index, artifact in enumerate(artifacts):
            venv = outside / f"venv-{index}"
            run(["uv", "venv", "--python", args.python, venv], outside, env=env)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            scripts = python.parent
            run(["uv", "pip", "install", "--python", python, "--require-hashes", "-r",
                 dist / "runtime-dependencies.txt"], outside, env=env)
            run(["uv", "pip", "install", "--python", python, "--no-deps", artifact], outside, env=env)
            run(["uv", "pip", "check", "--python", python], outside, env=env)
            run([python, "-I", smoke, "--expect-prefix", venv], outside, env=env)
            cli = scripts / ("anomalyzer.exe" if os.name == "nt" else "anomalyzer")
            mcp = scripts / ("anomalyzer-mcp.exe" if os.name == "nt" else "anomalyzer-mcp")
            run([cli, "--help"], outside, env=env, stdout=subprocess.DEVNULL)
            run([python, "-I", "-m", "anomalyzer", "--help"], outside, env=env,
                stdout=subprocess.DEVNULL)
            response = run([mcp], outside, env=env, capture_output=True, text=True,
                           input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
            payload = json.loads(response.stdout)
            assert {t["name"] for t in payload["result"]["tools"]} == {
                "analyze", "list_findings", "get_evidence"}
    print("Clean wheel and sdist consumer checks passed")


if __name__ == "__main__":
    main()
