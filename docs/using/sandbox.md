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
| [Docker over HTTP](../getting-started/http.md#compose) | a separate `worker` container with `network_mode: none`; inside it each job runs in its own bubblewrap mount namespace that binds only its workspace, so one client's script never sees another's. The HTTP container, which has a network, runs no scripts |

Every job also gets a timeout (default 240 s, `--timeout` or `B123D_PRINT_TIMEOUT`; a `check`
300 s, `--check-timeout` or `B123D_PRINT_CHECK_TIMEOUT`), a CPU limit and a [memory
limit](#memory). A check stops a little before its limit and returns the findings it has
([time limit](checks.md#time-limit)); anything else that runs out of time is killed.

## Memory

Each job may use `--max-memory` (default 2 GB, `B123D_PRINT_MAX_MEMORY`; `0` = no limit). A
script that allocates without bound, or a huge or decompressing reference model, then fails
with "the build used more than 2 GB of memory, the limit per job on this server" instead of
pushing the machine, or the worker container, into the kernel's out-of-memory killer, which
would stop other builds too. The server and the other jobs go on.

| Platform | How |
| --- | --- |
| Linux (bubblewrap, Docker, no sandbox) | `RLIMIT_DATA`, set in the job's process before bubblewrap starts, soft and hard alike, so the job cannot raise it (that needs `CAP_SYS_RESOURCE` outside its user namespace) |
| Windows | the Job Object's per-process memory limit (committed memory) |
| macOS | none: macOS does not enforce a per-process memory limit |

Why `RLIMIT_DATA` and not the alternatives: it counts what a build really uses (its heap,
anonymous memory, thread stacks), not its shared libraries or address space reserved and never
used. `RLIMIT_AS` counts those too, and they grow with the number of CPUs (a thread pool reserves
memory per core), so a cap that fits on one machine would break builds on a bigger one. A cgroup
per job would also count the page cache, but an unprivileged worker in a container cannot create
cgroups (Docker mounts `/sys/fs/cgroup` read-only), so the [Compose setup](../getting-started/http.md#compose)
puts a `mem_limit` on the whole worker container instead, as the backstop for what a per-process
limit does not cover; keep it at least `B123D_PRINT_MAX_BUILDS` × `B123D_PRINT_MAX_MEMORY` + 1 GB.
A job the kernel kills anyway is reported as "killed by the system, most likely because the
worker ran out of memory", not as a shutdown.

## What keeps workspaces apart

Over [HTTP](../getting-started/http.md) several clients share one server, each in its own
workspace (`workspaces/<name>`). What stops one client's script from reaching another's files
depends on the mode:

- **macOS (`sandbox-exec`) and Linux (bubblewrap):** the OS sandbox binds (or allows reads of)
  only the job's own workspace, the Python installation and the few system paths a build needs.
  Other workspaces, the job queue and the tokens file are not in that set — a script cannot read
  or write them. This is the boundary.
- **Docker over HTTP (compose):** the network-less `worker` container runs each job in its own
  bubblewrap namespace, as above, so the mounted volume's other workspaces, the job queue and the
  shared config are not visible to a running script, and no token is in the worker's environment.
- **Windows, and any mode with `B123D_PRINT_SANDBOX=none` (such as a single-container `docker
  run`):** there is **no OS boundary between workspaces**. The audit hook refuses the obvious
  reaches (other workspaces, the tokens file, the job queue, the server's environment) and all
  writes outside the job's own folders, but it is defense in depth, not a guarantee: treat a
  script as able to read anything the process can. Run the two-container compose setup, or
  bubblewrap/WSL2, for untrusted scripts, and give one deployment only to clients that may see
  each other's work.

The audit hook (no sockets, subprocesses or native libraries; no writes outside the job's folders;
no reads of other workspaces, the tokens file or the server environment) runs in every mode. Its
configuration is captured when it is installed and it avoids the names a script could rebind, which
raises the bar, but the standard library it builds on is not frozen, so the hook is **best-effort
defense in depth, not an isolation boundary on its own** — the OS sandbox or the container is.

The [build cache](../scripts/convention.md#big-and-multi-piece-projects) adds no new access. Only
the sandboxed worker reads and writes it, only in the part's own `out/.cache/` (a folder it could
already write), and it is used only when the job's output folder is the part's `out/`. It is
never followed through a link. Its key reads only the part's own folder; a build that read a
file elsewhere in the workspace is not saved. A piece's name never becomes a file name (entries
are named by hashes). A script can write its own cache entries, as it can write any file in its
`out/`: that changes only what this part builds, which the script decides anyway. The CLI builds
in your own process and never reads the cache.

`list_parts` reports the sandbox in use. `B123D_PRINT_SANDBOX=none` turns the OS sandbox off; the
Docker image defaults to this because for a single container the container itself is the sandbox.
The two-container compose deployment turns it back on in the `worker` (bubblewrap) so that clients
sharing one server are isolated from each other.

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
