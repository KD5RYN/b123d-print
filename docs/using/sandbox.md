# Sandbox

Part scripts are model-written code. The MCP server runs every build, render, section, check
and export in a separate process, isolated as far as the platform allows. `compare` runs there
too: the mesh files it parses may have been written by a part script.

| Platform | Isolation |
| --- | --- |
| macOS | `sandbox-exec`: no network, no child processes, writes only to the part's `out/` and a scratch folder, home folder unreadable except the workspace |
| Linux with [bubblewrap](https://github.com/containers/bubblewrap) | no network, read-only system, same writable folders, home hidden |
| Linux without bubblewrap | separate process + audit hook only — **install bubblewrap, or use Docker** |
| Windows | **no OS sandbox**: a separate process in a Job Object (CPU-time limit; on a timeout the whole job, with anything the script started, is killed) + the audit hook. A script can read any file your account can. For isolation run the server in [WSL2](https://learn.microsoft.com/windows/wsl/install) with bubblewrap, or in [Docker](../getting-started/docker.md) |
| [Docker](../getting-started/docker.md) | the container (`--network none`, only the mounted folder) |
| [Docker over HTTP](../getting-started/http.md#compose) | a separate `worker` container with `network_mode: none` runs the part scripts; the HTTP container, which has a network, runs none |

Every job also gets a timeout (default 120 s, `--timeout` or `B123D_PRINT_TIMEOUT`; a `check`
300 s, `--check-timeout` or `B123D_PRINT_CHECK_TIMEOUT`) and a CPU limit. A check stops a little
before its limit and returns the findings it has ([time limit](checks.md#time-limit)); anything
else that runs out of time is killed. The audit hook (blocks sockets, subprocesses, native libraries, writes elsewhere) is
defense in depth, not a boundary on its own.

`list_parts` reports the sandbox in use. `B123D_PRINT_SANDBOX=none` turns the OS sandbox off;
the Docker image does this because the container is the sandbox.

Over [HTTP](../getting-started/http.md) the same sandbox applies to every client's builds; the
bearer token decides who may run them at all, and `--max-builds` how many run at once. Over
[SSH](../getting-started/ssh.md) the key's `authorized_keys` line decides, and the same limit
holds across every connection.

Reference files for a [remix](remix.md) are parsed in the sandbox too (`describe_model`, and
`import_model` in a script): a file from the internet is untrusted input. Getting one onto the
server (`push` over SSH, the signed upload link over HTTP) writes only into
`parts/<part>/ref/`, only STL, 3MF and STEP up to 50 MB, never through a symlink.

The [CLI](../getting-started/cli.md) does **not** sandbox: it runs your own scripts like any
Python.

On Ubuntu 24.04, bubblewrap also needs unprivileged user namespaces allowed; see
[Troubleshooting](../troubleshooting.md).
