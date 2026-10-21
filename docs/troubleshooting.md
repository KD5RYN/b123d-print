# Troubleshooting

| Symptom | Fix |
| --- | --- |
| First start is very slow, or the client gives up | it is downloading the dependencies; run `uvx --from b123d-print b123d-print-mcp --help` once in a terminal, then restart the client |
| Bambu Studio says "The 3mf file has invalid config, load geometry data only" | expected: the file has no Bambu project settings, only the shape. Click OK; the part loads and you slice it with your own settings (Arrange with A if it lands off the plate) |
| Client says `uvx` not found | use the full path from `which uvx` (Windows: `where.exe uvx`) as the command |
| The assistant finished but the files are still on the server | ask it to bring the part home: `download_part`, then unzip in the project folder; if its shell has no network (Antigravity's `agy`), `download_part(name, embed=True)` and unzip the saved zip ([get the files](getting-started/http.md#get-the-files)) |
| Antigravity (`agy`) doesn't list the b123d-print tools | the remote key is `serverUrl`, not `url`; then `/mcp` to reload, or restart `agy` ([Antigravity](getting-started/mcp-clients.md#antigravity-agy-cli-and-ide)) |
| Antigravity asks before every tool call | allow `mcp(b123d-print/*)` in `permissions.allow` ([Antigravity](getting-started/mcp-clients.md#antigravity-agy-cli-and-ide)) |
| Model never looks at the renders | your client doesn't pass tool images to the model; open `out/images/*.png` yourself |
| `timed out after 240 s` | a slow or endless script. Read the timing report of `build_part` (or `b123d-print build`), build one piece at a time with `parts=`, and see [big and multi-piece projects](scripts/convention.md#big-and-multi-piece-projects); raise `--timeout` only if the part is genuinely heavy |
| `[FAIL] timeout ... time limit reached while running ...` | `check` ran out of time; the findings above it are complete. Raise `--check-timeout` (`B123D_PRINT_CHECK_TIMEOUT`), or narrow the check it names ([time limit](using/checks.md#time-limit)) |
| `blocked in part scripts: ...` | the script tried the network, a subprocess or files outside the workspace; part scripts only need build123d |
| `unknown setting(s)` | a typo in `config.toml` or `b123d-print.toml`; the message lists the known keys ([Settings](using/settings.md)) |
| HTTP server exits right after starting | it prints why: a missing or short token, an unreadable token file, a workspace it cannot write; see [Over the network](getting-started/http.md#if-it-does-not-start) |
| Holes print small | set the slicer's X-Y hole compensation from the [hole coupon](using/hole-compensation.md) |
| Windows: sandbox says "no OS sandbox here" | expected: Windows has none ([Sandbox](using/sandbox.md)); run the server in WSL2 with bubblewrap, or in [Docker](getting-started/docker.md), for untrusted scripts |
| Windows: install fails with a path-too-long error | the deepest file in the uv cache is about 165 characters below the cache folder; turn on [long paths](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation#enable-long-paths-in-windows-10-version-1607-and-later), or point `UV_CACHE_DIR` at a short folder such as `C:\uv` |
| Linux: sandbox says "audit hook only" | install bubblewrap (`apt install bubblewrap`); on Ubuntu 24.04 unprivileged user namespaces must also be allowed (`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`) — or use [Docker](getting-started/docker.md) |

## Print problems

When the part prints but comes out wrong. Tell the assistant what you see (a photo helps): it
changes the dimension with `set_params` and rebuilds, rather than rewriting the script.

| Symptom | Fix |
| --- | --- |
| A fit is too tight or too loose | print the [`fit_coupon`](scripts/examples.md#fit_coupon) and store your `clearance`, `press_fit` and `free_fit` ([Settings](using/settings.md)); for one part, `set_params(name, "CLEARANCE=0.25")`. Test the next try with a [fit-test template](using/templates.md) |
| Holes too small, or a screw doesn't go in | set the slicer's X-Y hole compensation from the [hole coupon](using/hole-compensation.md); if you opted in to `hole_comp`, keep the slicer's at 0 ([From part to print](using/slicing.md)) |
| Holes lying on their side sag, string or come out oval | they need a teardrop or flat roof (the `holes` check warns about round ones), or turn the part so they are vertical ([recipes](using/recipes.md)) |
| Corners lift, the part warps | ABS, ASA, PC and nylon warp over ~100 mm: rounded footprint corners, ribs, a brim and an enclosure ([BP-B3, B4](BEST_PRACTICES.md)); PLA and PETG rarely do: check bed adhesion |
| A tall, thin part fell over or wobbled | brim (5-10 mm) or mouse ears; the tip-over check warns, `suggest_orientation` may lay it down |
| Rough faces where supports were | turn the part or chamfer the overhang ([From part to print](using/slicing.md#settings-the-part-assumes)); the print sheet lists which faces need support |
| It broke along a layer line | the load ran across the layers: lay it down so the load runs along them (`suggest_orientation` with `load=`), more walls ([design guide](DESIGN_GUIDE.md)) |
| The part is bigger than the bed | set your [printer](using/printer-profiles.md) so the `fit` check catches it, then [split it](using/splitting.md) |
| The assistant skipped the checks or didn't look at the renders | ask it to run the `verify_part` prompt (or "verify the part before I print it"): a full review with sections and checks, no changes ([MCP tools and prompts](using/tools.md)) |

Still stuck? [Open an issue](https://github.com/KD5RYN/b123d-print/issues) with the output of
`b123d-print --version`, `b123d-print config` and the error.
