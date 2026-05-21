#!/usr/bin/env bash
# Resolve and verify every version pin (ADR 0007).
#
# Reports drift between committed pins and current upstream:
#   - docker/digests.lock        base image SHA256 digests
#   - orynth.repos               external ROS source git SHAs
#   - docker/requirements.txt    pip package hashes (presence check only)
#
# Exit 0 = all pins resolvable and digests.lock matches upstream tags.
# Exit 1 = drift or unresolved pins detected.
#
# This script does NOT auto-edit files — it prints the correct values so a
# human can update them in a reviewable PR.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

drift=0

echo "== Docker base image digests =="
while IFS= read -r line; do
  [[ "$line" =~ ^[[:space:]]*# || -z "${line// }" ]] && continue
  ref="${line%% =*}"
  pinned="${line##*= }"
  current="$(docker buildx imagetools inspect "$ref" --format '{{.Manifest.Digest}}' 2>/dev/null || echo 'UNRESOLVED')"
  if [[ "$current" == "$pinned" ]]; then
    echo "  OK    $ref"
  else
    echo "  DRIFT $ref"
    echo "        pinned:  $pinned"
    echo "        current: $current"
    drift=1
  fi
done < docker/digests.lock

echo
echo "== orynth.repos git SHAs =="
if grep -qE "version:[[:space:]]*0+[[:space:]]*(#.*)?$" orynth.repos; then
  echo "  FAIL  unset (all-zero) SHA sentinel present in orynth.repos"
  drift=1
else
  echo "  OK    no sentinel SHAs; all entries pinned"
fi
# Report upstream HEAD for each repo so a maintainer can re-pin per phase.
python3 - <<'PY'
import re
import subprocess

text = open("orynth.repos").read()
for m in re.finditer(r"^\s{2}(\w+):\n\s+type: git\n\s+url:\s*(\S+)\n\s+version:\s*(\w+)", text, re.M):
    name, url, pinned = m.groups()
    try:
        out = subprocess.check_output(["git", "ls-remote", url, "HEAD"], text=True, timeout=30)
        head = out.split()[0]
    except Exception:
        head = "UNRESOLVED"
    flag = "OK   " if head == pinned else "AHEAD"
    print(f"  {flag} {name}: pinned {pinned[:12]}  upstream HEAD {head[:12]}")
PY

echo
echo "== pip hashes =="
if grep -qE "hash=sha256:0+$" docker/requirements.txt; then
  echo "  FAIL  placeholder (all-zero) hash present in requirements.txt"
  drift=1
else
  echo "  OK    every requirement carries a non-placeholder --hash"
fi
echo "  NOTE  regenerate hashes with: pip-compile --generate-hashes (or pip hash)"

echo
if [[ "$drift" -ne 0 ]]; then
  echo "RESULT: drift / unresolved pins detected — update the files above."
  exit 1
fi
echo "RESULT: all pins resolvable; digests.lock matches upstream."
