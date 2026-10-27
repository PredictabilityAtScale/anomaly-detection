#!/usr/bin/env bash
# Run from repository root. Only artifacts and the smoke script enter the containers.
set -euo pipefail
image=public.ecr.aws/lambda/python:3.12
root=$(pwd)
bundle="$root/.tmp/lambda-consumer"
mkdir -p "$bundle"
if [ -e "$bundle/package" ]; then
  echo "Use a fresh .tmp/lambda-consumer directory for each verification" >&2
  exit 1
fi
docker pull --platform linux/amd64 "$image"
docker image inspect "$image" --format '{{json .RepoDigests}}' > "$bundle/image-digests.json"
docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
  -v "$root/dist:/artifacts:ro" -v "$bundle:/output" "$image" -euc '
    cd /tmp
    python -m pip download --only-binary=:all: --require-hashes \
      --find-links /artifacts -r /artifacts/requirements-offline.txt -d /output/wheelhouse
    python -m pip install --no-index --only-binary=:all: --require-hashes \
      --find-links /output/wheelhouse -r /artifacts/requirements-offline.txt \
      --target /output/package --no-compile
    cp /artifacts/requirements-offline.txt /output/requirements-offline.txt
    cd /output/wheelhouse
    sha256sum *.whl > /output/wheelhouse-SHA256SUMS
    python -m pip --version
  '
docker run --rm --platform linux/amd64 --network none --entrypoint /bin/bash \
  -v "$bundle/package:/var/task:ro" \
  -v "$root/examples/library/guard_smoke.py:/tmp/guard_smoke.py:ro" \
  -w /var/task "$image" -euc \
  'PYTHONPATH=/var/task python /tmp/guard_smoke.py --expect-prefix /var/task' \
  | tee "$bundle/smoke.json"
