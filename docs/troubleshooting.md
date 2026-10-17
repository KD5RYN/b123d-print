# Troubleshooting

| Symptom | Fix |
| --- | --- |
| First start is very slow, or the client gives up | it is downloading the dependencies; run `uvx --from b123d-print b123d-print-mcp --help` once in a terminal, then restart the client |
| Client says `uvx` not found | use the full path from `which uvx` as the command |
| Model never looks at the renders | your client doesn't pass tool images to the model; open `out/*.png` yourself |
| `timed out after 120 s` | a slow or endless script; raise `--timeout` if the part is genuinely heavy |
| `blocked in part scripts: ...` | the script tried the network, a subprocess or files outside the workspace; part scripts only need build123d |
| `unknown setting(s)` | a typo in `config.toml` or `b123d-print.toml`; the message lists the known keys ([Settings](using/settings.md)) |
| HTTP server exits right after starting | it prints why: a missing or short token, an unreadable token file, a workspace it cannot write; see [Over the network](getting-started/http.md#if-it-does-not-start) |
| Holes print small | calibrate `hole_comp` with the [coupon](using/hole-compensation.md) |
| Linux: sandbox says "audit hook only" | install bubblewrap (`apt install bubblewrap`); on Ubuntu 24.04 unprivileged user namespaces must also be allowed (`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`) — or use [Docker](getting-started/docker.md) |

Still stuck? [Open an issue](https://github.com/KD5RYN/b123d-print/issues) with the output of
`b123d-print --version`, `b123d-print config` and the error.
