# FAQ

Short answers, each with a link to the page that has the details.

## Getting started

**Do I need to know CAD or Python?**
No. You describe the part and give a few measurements; the assistant writes the part script (a
Python file in `parts/<name>/`), builds it, looks at it and checks it. Knowing a little helps you
change a number yourself, but [`set_params`](using/tools.md) and `b123d-print set` do that too.
See [How a session goes](using/workflow.md).

**Which assistant should I use? Does it cost anything?**
b123d-print is free and open source (MIT). Any MCP client works; the best results come from a
model that can **see images**, because the workflow has it look at its own renders and sections.
The clients, what each supports, and how to connect it: [Connect your MCP client](getting-started/mcp-clients.md#which-clients).
What the assistant costs is up to its provider.

**The plugin, the MCP server or Docker: which one?**
They all run the same MCP server.

- **Claude Code plugin:** one command in Claude Code, the server plus a skill, the project folder
  as workspace ([Claude Code](getting-started/mcp-clients.md#claude-code)).
- **MCP server through `uvx`:** for every other client (Claude Desktop, Cursor, Gemini CLI, Antigravity, ...):
  a few lines in the client's config ([Quick start](getting-started/quick-start.md)).
- **Docker:** the strongest isolation (the way to get a real sandbox on Windows), or the shared
  HTTP server for several machines ([Docker](getting-started/docker.md), [Which mode?](advanced/index.md)).

**The install failed, or the first start times out.**
The first start downloads build123d, OpenCascade and the rest, which takes a while. Run
`uvx --from b123d-print b123d-print-mcp --help` once in a terminal, then restart the client. If
the client says `uvx` isn't found, use its full path. More in [Troubleshooting](troubleshooting.md).

**Can I use it without an AI?**
Yes: the `b123d-print` CLI builds, checks, exports and makes templates from part scripts you
write yourself ([CLI and Python](getting-started/cli.md)).

**How do I update?**
It depends on how you installed it; for `uvx`, `uvx --refresh ...` once, then restart the client
([Updating](updating.md)).

## Parts and printing

**What units?**
Millimeters, everywhere: the scripts, the checks and the files (3MF stores the unit; STL has
none, and slicers read it as millimeters). Give inches if you like: the assistant converts them and
confirms each value in mm ([Measuring for the AI](using/measuring.md)).

**Why did it ask me ten questions before modeling?**
On purpose. A part is only as good as its measurements: the assistant lists every dimension it
read, asks for the ones that decide the fit, and waits for you to confirm, rather than guess
([Measuring for the AI](using/measuring.md), [workflow rules](scripts/rules.md)).

**Why do holes print small?**
Every FDM printer prints holes a little undersize. b123d-print models holes true to size, and
the slicer corrects them: print the hole coupon once per printer and material and enter half
its diameter error in the slicer's **X-Y hole compensation**
([Hole compensation](using/hole-compensation.md)). Building it into the files instead
(`hole_comp`) is an opt-in.

**How accurate will it be?**
About as accurate as your printer and your measurements: ±0.2 mm is normal for FDM. The fits
(`clearance`, `press_fit`, `free_fit`) are per printer and material; print the
[fit coupon](scripts/examples.md#fit_coupon) once and store the values. Before a long print, test the fit with
a quick [fit-test template](using/templates.md).

**What if the part doesn't fit my printer's bed?**
Set your printer ([Printer profiles](using/printer-profiles.md)) and the `fit` check fails when a
part is too big; the assistant then proposes where to cut and how to join the pieces
([Splitting parts](using/splitting.md)).

**How do I take it into my slicer?**
Open the `.3mf` in Bambu Studio, OrcaSlicer or PrusaSlicer; it is already in print orientation.
Walls, supports, the Bambu "invalid config" message, several pieces and the print sheet:
[From part to print](using/slicing.md).

**Can I edit the result in Fusion, Onshape or FreeCAD?**
Yes: open the `.step`, an exact solid without feature history. Changes there don't flow back to the
script; the script stays the parametric source ([Output formats](using/formats.md)).

**Resin printers, CNC, laser cutting?**
No: the rules and checks are for FDM printing (overhangs, bridges, layer strength, bed edges).
The STEP file is a normal solid you can take elsewhere, but nothing here checks it for those.

**Where do the files go?**
Locally, into your workspace: `parts/<name>/<name>.py` (the script) and `parts/<name>/out/`,
sorted into folders: `out/print/` (3MF, STL: for the slicer), `out/cad/` (STEP), `out/images/`
(PNG previews and section views) and `out/docs/`; `out/README.md` says what is where. On a remote
server they live on the server until `download_part` brings them home ([Output formats](using/formats.md#where-each-file-goes),
[Which mode?](advanced/index.md)). Only the script, `ref/` and `b123d-print.toml` need keeping:
[What to save](using/what-to-save.md).

**The assistant says the part is done, but the files aren't in my project folder.**
On a remote server it must still bring them home: a remote `export` ends with a NEXT STEP
saying so, but some agents skip it. Ask for `download_part` and an unzip into the project
folder. If its shell has no network (Antigravity's `agy` with the terminal sandbox on),
`download_part(name, embed=True)` returns the zip inside the result, and `unzip` works offline
([Antigravity](getting-started/mcp-clients.md#antigravity-agy-cli-and-ide)). Locally (stdio) the
files are written straight into the project folder.

**A big part times out.**
Each build has 240 s. The build's timing report names the slow piece; build one piece at a time
with `parts=`, reuse a piece instead of building it twice, and use fewer points in curves
([big and multi-piece projects](scripts/convention.md#big-and-multi-piece-projects)). Raise
`--timeout` only for a genuinely heavy part; MCP clients wait about 300 s for a result
([server options](getting-started/mcp-clients.md#server-options)).

**The print came out wrong.**
See [Print problems](troubleshooting.md#print-problems). Bring the photo back to the assistant:
it can change the dimension with `set_params` and rebuild. To report a bug in b123d-print, open an
[issue](https://github.com/KD5RYN/b123d-print/issues) with the part script and what went wrong.

## Privacy, network and safety

**Does it send my parts anywhere?**
No. Run locally, the server has no telemetry and opens no network connections of its own; the
only network use is `uvx` downloading the package from PyPI. Your parts stay in your workspace.
The **assistant** sees what you send it and what the tools return (text and renders), under
its provider's terms. Remote modes ([SSH](getting-started/ssh.md), [HTTP](getting-started/http.md))
send the parts to the server you set up, and nowhere else.

**Does it work offline?**
The server and the 3D view do (the viewer ships inside the package and loads nothing). Your
assistant usually doesn't, unless it is a local model.

**The AI writes code that runs on my computer: is that safe?**
Part scripts run in a separate process with a time limit and, where the system has one, an OS
sandbox: no network, writes only to the part's `out/` folder ([Sandbox](using/sandbox.md)).

**It says "OS sandbox off", "no OS sandbox here" or "audit hook only".**
The scripts still run in a separate process with a time limit, but without the OS sandbox. On
**Linux** install bubblewrap (`apt install bubblewrap`). On **Windows** there is no OS sandbox:
use WSL2 with bubblewrap, or Docker, for scripts you don't trust. In the **Docker** image
"sandbox off" is expected: the container is the sandbox. See [Sandbox](using/sandbox.md) and
[Troubleshooting](troubleshooting.md).

## Windows

**Does it work on Windows?**
Yes, with three things to know: there is no OS sandbox (above); an install can fail on a long
path (turn on long paths, or set `UV_CACHE_DIR` to a short folder such as `C:\uv`); desktop apps
may not find `uvx` (use the full path from `where.exe uvx`). Details in
[Troubleshooting](troubleshooting.md).
