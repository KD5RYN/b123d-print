# Sandbox

Part scripts are model-written code. The MCP server runs every build, render, section, check
and export in a separate process, isolated as far as the platform allows. `compare` runs there
too: the mesh files it parses may have been written by a part script.

| Platform | Isolation |
| --- | --- |
| macOS | `sandbox-exec`: no network, no child processes, writes only to the part's `out/` and a scratch folder, home folder unreadable except the workspace |
| Linux with [bubblewrap](https://github.com/containers/bubblewrap) | no network, read-only system, same writable folders, home hidden |
| Linux without bubblewrap, Windows | separate process + audit hook only — **install bubblewrap, or use Docker** |
| [Docker](../getting-started/docker.md) | the container (`--network none`, only the mounted folder) |
| [Docker over HTTP](../getting-started/http.md#compose) | a separate `worker` container with `network_mode: none` runs the part scripts; the HTTP container, which has a network, runs none |

Every job also gets a timeout (default 120 s, `--timeout` or `B123D_PRINT_TIMEOUT`) and a CPU
limit. The audit hook (blocks sockets, subprocesses, native libraries, writes elsewhere) is
defense in depth, not a boundary on its own.

`list_parts` reports the sandbox in use. `B123D_PRINT_SANDBOX=none` turns the OS sandbox off;
the Docker image does this because the container is the sandbox.

Over [HTTP](../getting-started/http.md) the same sandbox applies to every client's builds; the
bearer token decides who may run them at all, and `--max-builds` how many run at once. Over
[SSH](../getting-started/ssh.md) the key's `authorized_keys` line decides, and the same limit
holds across every connection.

The [CLI](../getting-started/cli.md) does **not** sandbox: it runs your own scripts like any
Python.

On Ubuntu 24.04, bubblewrap also needs unprivileged user namespaces allowed; see
[Troubleshooting](../troubleshooting.md).
