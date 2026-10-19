#!/usr/bin/env bash
# Everything CI runs that can run on this machine, before a push (see CONTRIBUTING.md):
#
#     tools/preflight.sh
#
# Runs every step even after a failure, then prints one summary line; exits 1 if any step failed.
# Steps that need something this machine lacks (docker for the real-ssh test, the claude CLI for
# the plugin checks) are reported as skipped, not passed. Logs: $PREFLIGHT_LOGS (default: a temp dir).
set -u
cd "$(dirname "$0")/.."
LOGS=${PREFLIGHT_LOGS:-$(mktemp -d "${TMPDIR:-/tmp}/preflight.XXXXXX")}
mkdir -p "$LOGS"
passed=() failed=() skipped=()

case "$(uname -s)" in
  Darwin) sandbox=sandbox-exec ;;
  Linux) sandbox=$(command -v bwrap > /dev/null && echo bubblewrap || echo "") ;;
  *) sandbox="Job Object" ;;
esac

step() {  # step NAME COMMAND...: run it, log to $LOGS/NAME.log, record the result
  local name=$1; shift
  printf '%-14s ' "$name"
  local t0=$SECONDS
  if "$@" > "$LOGS/$name.log" 2>&1; then
    passed+=("$name"); echo "ok    ($((SECONDS - t0)) s)"
  else
    failed+=("$name"); echo "FAIL  ($((SECONDS - t0)) s)  log: $LOGS/$name.log"
  fi
}

skip() { printf '%-14s skip  (%s)\n' "$1" "$2"; skipped+=("$1"); }

ssh_in_docker() {  # the real-sshd test on Linux in a throwaway container (bubblewrap needs --privileged)
  tar --exclude=./.venv --exclude=./site --exclude=./dist --exclude=./.git -cf - . |
    docker run --rm -i --privileged -v b123d-preflight-uv:/root/.cache/uv ghcr.io/astral-sh/uv:python3.12-bookworm sh -ec '
      apt-get update -qq && apt-get install -y -qq bubblewrap openssh-server > /dev/null && mkdir -p /run/sshd
      mkdir /w && tar -xf - -C /w && cd /w && uv sync --frozen -q
      B123D_PRINT_EXPECT_SANDBOX=bubblewrap sh tests/ssh_e2e.sh'
}

uv sync --frozen -q || { echo "uv sync --frozen failed"; exit 1; }

step unit env LANG=C LC_ALL=C uv run pytest -q -n auto
step check uv run b123d-print check
step e2e-stdio env ${sandbox:+B123D_PRINT_EXPECT_SANDBOX="$sandbox"} uv run python tests/mcp_smoke.py
if [ "$(uname -s)" = Linux ] && command -v bwrap > /dev/null && { command -v sshd > /dev/null || [ -x /usr/sbin/sshd ]; }; then
  step ssh env B123D_PRINT_EXPECT_SANDBOX=bubblewrap sh tests/ssh_e2e.sh
elif command -v docker > /dev/null && docker info > /dev/null 2>&1; then
  step ssh ssh_in_docker
else
  skip ssh "needs docker, or Linux with bubblewrap and sshd"
fi
step docs env NO_MKDOCS_2_WARNING=1 uv run mkdocs build --strict
if command -v claude > /dev/null; then
  step plugin claude plugin validate --strict ./plugin
  step marketplace claude plugin validate --strict ./
else
  skip plugin "claude CLI not on PATH"
fi

summary="passed ${#passed[@]}: ${passed[*]:-none}; failed ${#failed[@]}: ${failed[*]:-none}; skipped ${#skipped[@]}: ${skipped[*]:-none}"
if [ ${#failed[@]} -eq 0 ]; then
  echo "preflight PASS ($summary)"
else
  echo "preflight FAIL ($summary)"
  exit 1
fi
