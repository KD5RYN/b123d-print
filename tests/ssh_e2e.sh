#!/bin/sh
# The MCP smoke test over real ssh: a throwaway sshd (as the current user, on a free localhost
# port) with an authorized_keys line written by `b123d-print setup-ssh`.
#
#     sh tests/ssh_e2e.sh          (needs sshd: on Ubuntu `apt-get install openssh-server`)
set -eu
D=$(mktemp -d)
trap 'kill $(cat "$D/sshd.pid" 2>/dev/null) 2>/dev/null || true; rm -rf "$D"' EXIT
PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
SSHD=$(command -v sshd || echo /usr/sbin/sshd)

ssh-keygen -q -t ed25519 -N "" -f "$D/hostkey"
ssh-keygen -q -t ed25519 -N "" -C smoke -f "$D/client"
uv run b123d-print setup-ssh --key "$D/client.pub" --workspace "$D/ws" --host 127.0.0.1 --add --authorized-keys "$D/authorized_keys"
# Match the smoke fixture: a hang guard above legitimate coupon metrics, still below
# the production default (240 seconds), so the runaway script is killed sooner
sed -i.bak 's/ --dest / --timeout 120 --dest /' "$D/authorized_keys"
cat "$D/authorized_keys"

cat > "$D/sshd_config" <<EOF
Port $PORT
ListenAddress 127.0.0.1
HostKey $D/hostkey
PidFile $D/sshd.pid
AuthorizedKeysFile $D/authorized_keys
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM no
StrictModes no
SetEnv XDG_CONFIG_HOME=$D/config
EOF
"$SSHD" -f "$D/sshd_config" -E "$D/sshd.log"
for _ in $(seq 50); do [ -s "$D/sshd.pid" ] && break; sleep 0.1; done

SSH="ssh -p $PORT -i $D/client -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=$D/known_hosts -o LogLevel=ERROR"
DEST="$(id -un)@127.0.0.1"
$SSH "$DEST" version || { cat "$D/sshd.log"; exit 1; }
B123D_PRINT_SMOKE_SSH="$SSH $DEST" B123D_PRINT_SMOKE_WORKSPACE_DIR="$D/ws" uv run python tests/mcp_smoke.py --ssh \
    || { tail -30 "$D/sshd.log"; exit 1; }
