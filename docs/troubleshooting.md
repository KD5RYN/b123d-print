# Troubleshooting

| Symptom | Fix |
| --- | --- |
| First start is very slow, or the client gives up | it is downloading the dependencies; run `uvx --from b123d-print b123d-print-mcp --help` once in a terminal, then restart the client |
| Bambu Studio says "The 3mf file has invalid config, load geometry data only" | expected: the file has no Bambu project settings, only the shape. Click OK; the part loads and you slice it with your own settings (Arrange with A if it lands off the plate) |
| Client says `uvx` not found | use the full path from `which uvx` (Windows: `where.exe uvx`) as the command |
| Model never looks at the renders | your client doesn't pass tool images to the model; open `out/*.png` yourself |
| `timed out after 240 s` | a slow or endless script. Read the timing report of `build_part` (or `b123d-print build`), build one piece at a time with `parts=`, and see [big and multi-piece projects](scripts/convention.md#big-and-multi-piece-projects); raise `--timeout` only if the part is genuinely heavy |
| `[FAIL] timeout ... time limit reached while running ...` | `check` ran out of time; the findings above it are complete. Raise `--check-timeout` (`B123D_PRINT_CHECK_TIMEOUT`), or narrow the check it names ([time limit](using/checks.md#time-limit)) |
| `blocked in part scripts: ...` | the script tried the network, a subprocess or files outside the workspace; part scripts only need build123d |
| `unknown setting(s)` | a typo in `config.toml` or `b123d-print.toml`; the message lists the known keys ([Settings](using/settings.md)) |
| HTTP server exits right after starting | it prints why: a missing or short token, an unreadable token file, a workspace it cannot write; see [Over the network](getting-started/http.md#if-it-does-not-start) |
| Holes print small | calibrate `hole_comp` with the [coupon](using/hole-compensation.md) |
| Windows: sandbox says "no OS sandbox here" | expected: Windows has none ([Sandbox](using/sandbox.md)); run the server in WSL2 with bubblewrap, or in [Docker](getting-started/docker.md), for untrusted scripts |
| Windows: install fails with a path-too-long error | the deepest file in the uv cache is about 165 characters below the cache folder; turn on [long paths](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation#enable-long-paths-in-windows-10-version-1607-and-later), or point `UV_CACHE_DIR` at a short folder such as `C:\uv` |
| Linux: sandbox says "audit hook only" | install bubblewrap (`apt install bubblewrap`); on Ubuntu 24.04 unprivileged user namespaces must also be allowed (`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`) — or use [Docker](getting-started/docker.md) |

Still stuck? [Open an issue](https://github.com/KD5RYN/b123d-print/issues) with the output of
`b123d-print --version`, `b123d-print config` and the error.
