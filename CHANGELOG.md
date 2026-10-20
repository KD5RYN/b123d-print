# Changelog

## 0.3.5 — unreleased

- **HTTP: the workspace is resolved once.** The auth layer works out the request's workspace and the
  tools use exactly that one. A request that names the workspace more than once, or differently in
  `?workspace=` and the `X-B123D-Workspace` header, is refused with 400. Upgrade shared HTTP servers
  with named tokens.

## 0.3.4 — 2026-10-19

**Fix and adjust parts with fewer rewrites and less guessing**
([docs](https://kd5ryn.github.io/b123d-print/using/tools/#build-failures-dimensions-and-measurements)):
- **Build-failure diagnosis.** A failed `build_part`, `render_preview`, `section`, `check` or
  `export` result now carries a `DIAGNOSIS`: the likely cause, where (file, line, function, code
  and the piece being built), the evidence read from the failing build123d call, and specific
  fixes ("fillet r 3 on edges between faces 4 mm wide: try r <= 1.9 (R in Dims: set_params(...))").
  Covers fillets and chamfers, 2D offsets (splines: offset a polyline), 3D offsets and shells,
  booleans (coplanar, tangent, slivers, "Unable to clean"), lofts, sweeps, extrusions, missing
  `Dims` fields, `build()` returning the wrong type, empty selections, missing imports, and
  timeouts, which now name the piece that was building (the worker reports its progress). A
  build that runs but is invalid, empty, 2D or off the bed gets `problems` in `build_part`.
  New tool `diagnose_failure` (CLI `b123d-print diagnose`): each piece built on its own, the
  largest fillet radius that works, bad faces and edges, tiny edges and sliver faces of an
  invalid solid, and whether `fix()` repairs it.
- **Change one dimension.** New tools `params` (the `Dims` fields with type, value and source
  comment, derived values, variant overrides; read from the ast, never run) and `set_params`
  (an exact in-place edit of the defaults, or of a variant's overrides, that keeps comments and
  formatting; refuses unknown fields, expression defaults and wrong types; rebuilds and reports
  size and volume before and after, with the call that undoes it). CLI: `b123d-print params`,
  `b123d-print set <part> FIELD=VALUE`.
- **Measure.** New tool `measure` (CLI `b123d-print measure`): the gap between two pieces or
  assembly labels (stand-ins included) or their interference volume, a wall's thickness at a
  point, the distance or angle between two flat faces from `list_faces`, and a hole's diameter,
  printed size after `hole_comp` and depth; in mm with the points, and an optional highlight
  picture.

**Fit between pieces** ([docs](https://kd5ryn.github.io/b123d-print/using/fit/)): `check_fit`
(MCP), `b123d-print fit` (CLI) and the `Mates` check for `checks(d)`, on the pieces of
`assembly(d)` as placed, stand-ins included.
- **Interference:** pairs that overlap (FAIL, with the volume, center and extent of the overlap)
  and pairs closer than the clearance without touching (WARN, with the gap and where); faces
  resting on each other are contact. Male/female joint pairs (a script's `joints(d)`, or
  `Mates(joints=...)`) are measured against their own clearance.
- **Hole alignment:** round holes of two pieces on one axis are partners (a counterbore and its
  clearance hole count as one hole); partners further than `hole_tol` (0.2 mm) apart fail, and
  their diameters are read as M2-M6 screw holes (ISO 273 clearance, pilot, CNC Kitchen insert):
  a pair no single screw explains warns, as does a hole whose axis runs into solid material of
  the next printed piece. Bounding-box pre-filter and a pair cap keep it fast.

**Outline tracing** ([docs](https://kd5ryn.github.io/b123d-print/using/tracing/)): `trace_outline`
(MCP) and `b123d-print trace` turn a flatbed scan or a photo on a grid into a 2D outline in mm,
with its holes. Scale from the scan's DPI (read from the file), a grid's cell size, a credit card
or other rectangle of known size, or two points a known distance apart. Otsu threshold, grid
lines cleaned away, sub-pixel contour, simplified to a tolerance in mm (or spline through-points);
writes the points (JSON), a snippet for the part script and an overlay PNG to confirm. Uses only
what was already installed (numpy, scipy, Pillow and contourpy via matplotlib) and runs in the
sandbox. `upload_reference` and `b123d-print push` now also take PNG, JPEG, TIFF and BMP images.

**Recipe library** ([docs](https://kd5ryn.github.io/b123d-print/using/recipes/)): twelve tested
build123d recipes in `b123d_print.recipes`, served by the `recipe` tool, the
`b123d-print://recipes` resources and `b123d-print recipes`: teardrop / flat-roof holes,
counterbores and countersinks (sized from bd_warehouse's fastener tables), hex nut traps, magnet pockets, snap arms with strain sizing,
living hinges, print-in-place hinges, lids with a lip, embossed and debossed text, a fillet-safe
bed chamfer, zip-tie and cable slots, ribs and gussets. Each has printing notes and sources, and
its demo part is built and passes `check` in the tests.
- `AGENTS.md`: trace a scan instead of measuring an outline point by point, use a recipe before
  improvising a feature, run the fit check on assemblies.

**Measuring for the AI**, a new guide ([docs](https://kd5ryn.github.io/b123d-print/using/measuring/)):
how to measure a real object and hand the numbers over, especially large, complex or curved
parts. Which method for which part (calipers, a flatbed scan or a photo on a grid, profile
gauges and bent wire for curves, a **table of offsets** at fixed stations along a datum for large
parts), the common errors (Abbe error, the tape's hook, level vs along the surface, parallax and
lens distortion), how to photograph with a scale reference, a copy-paste measurement sheet and
offsets table (units, datum, accuracy, CONFIRMED or estimated, a `MEASURE.md` as the source of
truth), checking with a fit-test template, a 1:1 print-out or a test section, and worked
examples including a 1.5 m curved trim. Sourced.
- The workflow rules (`AGENTS.md`) and the `design_part_from_photos` prompt: ask for
  units, a datum, the critical dimensions and their accuracy; suggest the method for the part's
  size and shape and an offsets table for large or curved ones; ask for a scale in photos;
  record confirmed values in `Dims` with their source and accuracy.

**Big and multi-piece projects** without rebuilding everything for every step
([docs](https://kd5ryn.github.io/b123d-print/scripts/convention/#big-and-multi-piece-projects)):
- **Build cache.** The MCP server's sandboxed worker saves each piece it builds (and the
  assembly) as BREP in the part's `out/.cache/`; `build_part`, `render_preview`, `section`,
  `check`, `export` and the other tools read it back instead of building again. Keyed by every
  `.py` file in the part's folder, the variant and its Dims, the settings a build can read, the
  versions of b123d-print, build123d and OCP, and the hash of every other file the build read in
  the part's folder. A miss or a broken entry rebuilds. Not cached: builds that read a file
  elsewhere in the workspace, remixes that load a model (`import_model` has its own cache), and
  `original(d)`. `fresh=true` on those tools rebuilds; `B123D_PRINT_NO_CACHE=1` turns it off.
  The cache stays inside the part's `out/` folder and never widens what a script can read or
  write.
- **One piece at a time.** `build(d)` may return a dict of zero-argument functions (lazy
  pieces), each built only when needed. `build_part` gained `parts=`; `parts=` on
  `render_preview`, `section` and `export` now builds only those pieces. CLI: `b123d-print build
  --only a,b` and `uv run parts/x/x.py --only a,b`. Plain shapes work as before.
- **Where the time goes.** `build_part` and `b123d-print build` report each piece's face count
  and build time (and whether it was cached), with a hint for a piece over ~1,500 faces or
  ~10 s: dense polyline or many stacked offsets: fewer curve points, a spline, or build once and
  mirror/copy the result.
- **The build time limit is now 240 s** (was 120): `--timeout`, `B123D_PRINT_TIMEOUT` and the
  compose/`.env` examples. That stays under the 300 s an MCP client waits for a result; checks
  keep their own 300 s limit.
- The workflow rules (`AGENTS.md`) have a "Big and multi-piece projects" section: build each
  distinct piece once and mirror it, keep curves to the points they need, use `parts=` instead
  of inventing variants, read the timing report, consider a script per piece.
- `tools/bench_multi_piece.py` times build + render + export of a six-piece part with and
  without the cache.

**Threads, fasteners and gears.** Part scripts can now import two build123d part libraries
([docs](https://kd5ryn.github.io/b123d-print/using/threads-fasteners-gears/)):
[bd_warehouse](https://github.com/gumyr/bd_warehouse) 0.4.0 (Apache-2.0: threads including
bottle threads, screws, nuts, heat-set inserts and their hole sizes, gears and worms, OpenBuilds
V-slot parts) and [py_gearworks](https://github.com/GarryBGoode/py_gearworks) 0.0.24 (Apache-2.0:
spur, helical, herringbone and bevel gears, racks). Both build inside the sandbox unchanged.
- A sourced guide: when to model a thread (M6 and up, coarse, upright, the user's clearance,
  faded ends) and when to use inserts, nuts or pilot holes instead; how bd_warehouse's holes
  meet `HOLE_COMP`, so a hole is compensated once (`InsertHole` cuts its table's drill size,
  0.19 mm over CNC Kitchen's 5.6 mm M4 hole); gears (module, backlash, profile shift, helical
  and herringbone, orientation, materials); mounting to 2020 V-slot.
- New examples: `jar_lid` (a 38-400 bottle thread), `insert_bracket` (M4 heat-set inserts and
  counterbored screw holes from bd_warehouse's tables), `gear_pair` (a meshed py_gearworks pair
  with profile shift and a backlash `Gap` check) and `vslot_mount` (a plate keyed into 2020
  V-slot, with the rail and T-nuts as stand-ins).
- The workflow rules (`AGENTS.md`) and the `design_part_from_photos` prompt say which library to
  use for what, and to keep modeled threads to sizes that print.
- bd_vslot is not included: its rails fail to build with build123d 0.13.

**View in 3D**: turn a part around in the browser before printing, without a slicer
([docs](https://kd5ryn.github.io/b123d-print/using/formats/#3d-view-in-the-browser)).
- `export` makes a 3D view per variant (`view="print"`, the default: the printable parts on the
  bed; `"assembly"`: `assembly(d)` with its stand-ins; `"none"`). Over HTTP it returns a signed
  **view link** (`/view/...`: no token, bound to the workspace, expires with the download links),
  which `download_part` lists too; locally it writes a self-contained `out/<name>_view.html`
  (viewer and model inline: opens offline from `file://`). New CLI command `b123d-print view
  <part>` (`--assembly`, `--variant`, `--parts`, `--open`).
- The viewer: orbit, pan and zoom; the pieces listed with their sizes, each one to show or hide;
  the bed grid at Z = 0; the overall size and extent in mm and a bounding box; a section plane
  across X, Y or Z; iso, top, front and right views.
- Security: the view page is one static file with a strict Content-Security-Policy (scripts and
  styles from the server only, no inline script, `connect-src 'self'`, no framing),
  `nosniff`, `no-referrer`; the model is served as `model/gltf-binary`; piece names are shown as
  text; view signatures have their own purpose and never open other links (and the reverse).
  The offline HTML allows only its own inline scripts, by hash, and no network.
- New export format **`glb`** (binary glTF: one named, colored node per piece), for web and 3D
  apps; not in the default set (`all` now includes it).
- The viewer library, [three.js](https://threejs.org) r186 (MIT), is vendored in the package
  (640 KB, 160 KB gzipped): the server and the browser need no internet. Its license notice heads
  the bundle, ships as `three-LICENSE.txt` (listed in `license-files`) and travels inside every
  view HTML; `tools/vendor_viewer.py` rebuilds it from the npm tarball (integrity-checked) and
  records its provenance. `THIRD_PARTY.md` and the credits page list it.
- `AGENTS.md`: offer the 3D view after an export.
**Splitting parts**, a new guide ([docs](https://kd5ryn.github.io/b123d-print/using/splitting/))
and joint helpers for parts too big for the bed or better printed in pieces: when to split,
where to cut, a joint selection table, clearances per fit with the test-snippet habit (a
fit-test template of the joint), adhesives by gap, finishing seams, and worked examples (a long
trim split into keyed pieces). Sourced; new rules J6–J8 in BEST_PRACTICES, J2 and J3 updated.
- New module `b123d_print.joints`: `split(part, plane, joints, clearance)` cuts a part into two
  pieces with matching joint features. `Dowel` (round or square, loose or a plug), `Bowtie`
  (a butterfly key), `Dovetail`, `Lap` and `Insert` (the CNC Kitchen heat-set pocket, the
  screw's clearance hole and head access). The female is the male grown by the clearance on
  every side; loose keys and pins come back laid flat for printing, and placed for
  `assembly(d)`. Each joint's `pair(clearance)` gives the matching male and female on their own.
- New example `split_trim`: a 420 mm strip in two pieces with a bowtie key and square pins
  (variant `dovetail`), with `Gap` and `Wall` checks and fit-test templates of the joint.
- The workflow rules (`AGENTS.md`): a splitting step (propose cuts and a joint and wait, use the
  joints helpers, offer a fit test of the joint, add assembly notes).
- Corrections to commonly repeated advice: thin CA does not fill a 0.25–0.3 mm gap (epoxy or CA
  gel with activator does); "die swell" is real but the slicer's extrusion width absorbs it;
  elephant's foot, over-extrusion, corner bulge and faceted holes are what make fits tight.

**Print orientation**: a new MCP tool, `suggest_orientation(name, variant?, piece?, load?, image?)`,
and CLI command, `b123d-print orient`, rank the ways to put a part on the bed
([docs](https://kd5ryn.github.io/b123d-print/using/tools/#suggest_orientation)). The candidates
are the six axis-aligned orientations and every large flat face of the part's convex hull,
at most 12. Each is scored with the existing estimates: supports (bridges apart), print time,
bed contact, long bridges, tip-over and, with a `load` direction or the `structural` style,
how far the load points out of the layers (DS-T1). The result is a ranked table with the
`Rot(x, y, z)` to apply in `build(d)`, and says how (and what `UP` becomes). It never edits the
script.
- **tip-over**, a new automatic check (`TipOver`, warn only, rule B6): a part tall on a small
  first layer, which the nozzle can knock over. It measures with OrcaSlicer's Auto brim
  formula (height, and the footprint's width and second moment of area), plus a footprint
  that is a thin strip or a centre of mass outside it, and suggests a brim, mouse ears, laying
  the part down, or printing several together. The new `tip_speed` setting (200 mm/s) scales
  it; `0` turns it off.
- `design_metrics`' supports estimate is about 4 times faster on detailed parts, and lists the
  bridges it found.
- `AGENTS.md`: run `suggest_orientation` before exporting a part that isn't obviously
  flat-bottomed.

## 0.3.3 — 2026-10-19

**A `structural` design style** for parts that carry load: brackets, mounts, clamps, hooks,
hinges, gears, tool holders (also `strong`, `load_bearing`, `heavy_duty`). New sourced rules
DS-T1..T11 in the [design guide](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/#34-structural-load-bearing)
(load along the layers, walls before infill, filleted inside corners, wall thickness, ribs,
bolted joints, hole edge distance, material and heat, annealing, snap fits, slicer settings).
- `design_metrics` measures four more things for every part: **inside corners** (sharp,
  filleted, chamfered shares, and the smallest fillet radius over the wall it joins), **hole
  edge distance** (screw holes, in diameters), **slenderness across the layers** (a long run
  standing on a small section) and, for a style that sets `min_wall_lines`, the **thinnest
  walls** in line widths.
- New style-file thresholds `max_sharp_inside_share`, `min_inside_radius_ratio`,
  `min_wall_lines` and `max_z_slenderness`; `structural` uses them (0.1, 0.5, 3 lines, 5.6).
- New example `shelf_bracket`: an L with a brace, lying on its side, filleted and clean under
  the new style.
- The structural sources first read only as search text were fetched and checked: PETG's HDT
  is 72–76 °C (not 78), Prusa does not single out cubic infill, a washer gives bearing area (a
  compression limiter is what fights creep), and "less part cooling" was dropped (CNC Kitchen:
  PLA wants part cooling; too hot a nozzle hurts as much as too cold). MDPI, Xometry, Stratasys
  and Bambu Lab pages block automated access and stay marked *search, not fetched*.
- **Fixed:** the edge metric (M7) counted inside (concave) edges as sharp outside edges, so
  `max_sharp_edge_share` and `min_treated_edge_share` (rugged, soft, modern) over-reported parts
  with inside corners.
- The MCP `initialize` response names the server's version (`serverInfo.version` was empty).
- Releases publish the MCP Registry entry and open the plugin's pin bump on their own.
- The Claude plugin's version is now the server version it runs: a release leaves `plugin/` alone,
  and the plugin moves (version, pin and lock) when the release's plugin-pin pull request is merged.

## 0.3.2 — 2026-10-19

**Fit-test templates.** A quick thin print cut from the real part, to check its size, hole
pattern and mating fits before printing the whole part ([docs](https://kd5ryn.github.io/b123d-print/using/templates/)):
- Three kinds: **slice** (the part between two planes, `XY`/`XZ`/`YZ`), **face** (one flat face
  with its holes as a plate) and **crop** (the part inside a box). 1.2 mm thick by default; cut
  from the part as built, so hole compensation and clearances are the part's.
- Each is laid flat (template face down, centered), joined by a 1 mm base plate when it falls
  apart into pieces (or a crop has little to stand on), labeled `<part> <id>` where there is room
  (never through a feature; `label=False` for none), and checked like a part. A plane or box that
  misses the part is a clear error.
- MCP tools `list_faces` (flat faces with stable ids, normals, areas, round holes; `highlight`
  draws one in red to confirm it with the user) and `make_template` (writes
  `<name>_template_<id>.*`, a picture of where it comes from, the findings, download links over
  HTTP); prompt `fit_test`. CLI: `b123d-print faces` and `b123d-print template --slice | --face |
  --crop`.
- Part scripts may define `templates(d)` (`Template.slice`, `Template.face_of`, `Template.crop`):
  export writes them with every variant. The `esp_ir_blaster` example has two; the part template
  has a commented one.
- Python: `slice_template`, `face_template`, `crop_template`, `list_faces`.
- The workflow rules (`AGENTS.md`), prompts and skill: offer a fit-test template before the full
  print when a part mates with something or has a hole pattern, and confirm the face or region
  with the user first.
- `render` draws colors with alpha see-through (the highlight pictures).

**Fixed:** a server shutdown that arrived just after a build was claimed but before its process
started no longer lets that build run on until its timeout (also fixes a flaky CI test).

**Sharing:** `b123d-print mcp …` starts the MCP server (the same as `b123d-print-mcp`), so
`uvx b123d-print mcp` works; `server.json` describes the server for the MCP Registry
(`io.github.KD5RYN/b123d-print`); the docs show the one-command plugin install.

## 0.3.1 — 2026-10-18

**Bringing parts home from a remote server.** Over HTTP and SSH the server is a workbench, not
storage; clients now get the whole part back in one step, in the same layout a local install
writes into the project folder (`parts/<name>/<name>.py`, `out/`, `ref/`).
- `download_part(name, variant?, formats?, embed?)` (MCP tool): over HTTP one signed, expiring
  link (no token) to a zip of the whole part, `curl -fLo <name>.zip '<link>'` and unzip it in the
  project folder; also a `b123d-print://download/{workspace}/{part}` resource. Over SSH it gives
  the `b123d-print pull` command; locally it says the files are already there.
- `b123d-print pull` now copies the whole part (script, `out/`, `ref/`) into `parts/<part>/` of
  the project folder (`-o`, default the current folder) instead of only the `out/` files into
  `-o`; new `--variant`. Needs a 0.3.1 server (`ssh-serve` gains `pull --tree`); 0.3.0 clients
  still get what they got before.
- "MCP tools and links only, the server copy is temporary, never ssh/scp": in the descriptions of
  the tools that write files, in their results over HTTP and SSH (and in `check` once it passes),
  in the server's instructions, `AGENTS.md`, the Claude Code skill and the prompts, which end
  remote work with a required step: `download_part`, unzip, check the files are there, report.
- Over HTTP and SSH, results show workspace-relative paths only (also in error tracebacks and
  `list_parts`, which now names the workspace), never the server's own folders.

**Workspace retention (HTTP).** A named workspace nobody has used for 30 days is removed, checked
at startup and hourly and logged by name; never while a request or build for it is in flight.
`--retention-days` / `B123D_PRINT_RETENTION_DAYS` (`0` = never); in `deploy/compose.yaml` and the
new `deploy/.env.example`. The shared root workspace and SSH and local folders are never removed.

**Faster checks on remixes.** Checking a part made from a downloaded mesh (~10,000 triangles) is
several times faster:
- Section outlines no longer use `Wire.order_edges` and `Edge.positions`, which took seconds per
  section on the thousand-edge outlines of mesh-derived solids. A `Wall` check on such a section:
  14 s → 1 s; it also cuts its section once instead of twice.
- `Wall` measurements cast their rays against only the nearby part of the outline first
  (same results; a test compares them with the full cast).
- `ThinFeature` cuts mesh-derived parts from their triangulation from 400 mostly flat faces up
  (was: over 1500 faces).
- The checks on a remix's original are cached in `out/.cache/` (keyed by its geometry, the
  check, the settings and the b123d-print version): after the first `check`, only the remix is
  checked.
- A remix's thin spot that matches none of the original's listed spots is checked against the
  original's geometry, so knife edges the original already had are labeled inherited every time
  (four identical clips tie, and which one a section reports was arbitrary).
- `tools/bench_mesh_checks.py` times `check` on a generated 10,000-triangle remix.

**Parallel checks.** Over MCP (stdio, HTTP incl. the separate worker container, SSH; Windows
too) one `check` runs in up to `--max-builds` sandboxed workers at once, each with its share of
the checks (the original's included), balanced by an estimate of each check's cost; the server
merges the findings back in order. Workers still cannot start processes: the server starts
them, and each takes a build slot. Each worker builds the part from the cached conversion; the
first to need a mesh converted converts it while the others wait for it. One build slot, or a
small part, is one worker, as before. On the generated 41,000-triangle remix (Apple M4,
`tools/bench_mesh_checks.py --workers N`): 45 s → 30 s (3 workers) / 27 s (4) for the first
check, 26 s → 19 s / 16 s after. A worker takes ~3 s to start, so the 10,000-triangle remix
gains less: 10.8 s → 8.3 s first, 7.7 s → 6.5 s after (3 workers).

**Partial results at the time limit.** A `check` that runs out of time returns every finding it
finished, plus a `timeout` FAIL naming the check that was running and the ones not run, instead
of the worker being killed with nothing.

**A separate time limit for `check`:** `--check-timeout` / `B123D_PRINT_CHECK_TIMEOUT`, default
300 s (or `--timeout` if longer); builds, renders and exports keep `--timeout` (120 s).
`deploy/compose.yaml` reads both from `.env` (`B123D_PRINT_TIMEOUT`, `B123D_PRINT_CHECK_TIMEOUT`),
so a host can change them without editing the file.

## 0.3.0 — 2026-10-18

**Design review.** After the print checks pass, the assistant can review a part for its purpose
and a design style, and suggest changes; it never changes the part without your OK.
- Five styles: `functional` (default), `modern`, `least_cost`, `rugged`, `soft`. Set `STYLE` in
  `Dims` (variants can override it) or `style` in the workspace config. The industrial look is
  functional with `EDGES = "chamfer"`.
- `design_metrics` (MCP tool) and `b123d-print metrics` (CLI): size, filament (a simple estimate,
  roughly ±20 %) and cost, print time (one rule, a rough estimate), supports, shallow slopes that
  show layer steps, edge treatment (sharp / filleted / chamfered, distinct radii), mirror
  symmetry, likely screw sizes, seam corners and water traps; then the findings the style's
  thresholds trigger, each citing a `DS-*` rule.
- `design_review` prompt; a "Design review" step in `AGENTS.md`; `design_part_from_photos` asks
  for a style.
- Optional script fields `SHOW` (sides seen in use), `UP` (side up in use) and `EDGES`.
- Styles are TOML files: write your own in `~/.config/b123d-print/styles/` or the workspace's
  `styles/` folder, start from another with `based_on`, or replace a built-in by its name;
  `b123d-print styles` lists them.
- New settings `style`, `filament_price`, `print_flow`; material profiles gain `density`.
- [Design styles and review](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/): the rules
  (`DS-*`), sourced like the FDM design rules.

**Releases:** each version now gets a GitHub Release page made from its CHANGELOG section
(older versions are filled in too), and PyPI links to the changelog and releases.

## 0.2.1 — 2026-10-18

**Native Windows support for local use.** The MCP server and the CLI run on Windows 10/11 with
`uvx`, like on macOS and Linux; CI now tests Windows too (unit tests, MCP end to end over stdio
and HTTP).
- Part scripts run in a separate process inside a Job Object: a CPU-time limit, and on a timeout
  (or when the server stops) the worker and anything it started are killed together. There is
  **no OS sandbox** on Windows: process isolation and the audit hook only. Use WSL2 (with
  bubblewrap) or Docker when you need isolation; `list_parts` says which you have.
- The build limit shared by all server processes works on Windows too (`msvcrt` file locks).
- The audit hook also blocks `_winapi.CreateProcess` and registry writes, and compares paths
  case-insensitively on Windows.
- HTTP mode stops gracefully on Ctrl-Break (Windows has no SIGTERM); SIGHUP reload is POSIX only.
- Windows as an SSH client: `--ssh` keeps backslashes in paths (`ssh -i C:\Users\...`), and
  `pull`/`push` work with the built-in `ssh.exe`. SSH mode's server side stays macOS/Linux.
- CLI output no longer fails on a console that is not UTF-8 (characters it cannot show become `?`).

**Fixed:** HTTP mode behind a reverse proxy (Caddy) sometimes cut a reply off ("peer closed
connection without sending complete message body"): replies sent without reading the request body
(a 401/403, a refused upload link) now first read and discard it, up to 8 MiB; beyond that the reply
closes the connection.

## 0.2.0 — 2026-10-17

The part-script convention is unchanged from 0.1.0; existing scripts keep working.

**Remixing an existing model**
- `import_model("ref/bracket.stl")` loads an STL, 3MF or STEP as a solid to change. Meshes are
  welded, small gaps closed, triangles oriented, and coplanar triangles merged into planar
  faces (curves stay faceted); units are checked (`scale="inch"`), meshes over `max_triangles`
  (new setting, default 50,000) are refused with advice to simplify, the conversion is cached.
- Reference files go to `parts/<part>/ref/`: `b123d-print push` over SSH, the `upload_reference`
  tool (base64, or a signed upload link for `curl -fT`) over HTTP.
- New tools `describe_model` and `before_after`, prompt `remix_part`, command `b123d-print to-step`.
- The checks also run on the original: findings it already had are labeled *inherited from the
  original* and never fail the check. Exports of a remix add before/after and deviation images.
- New example `remix_bracket`.

**Faster**
- Tessellation reads triangles by index (rendering and the overhang check on a 9k-face solid:
  20 s -> 1 s each); the thin check slices the triangle mesh on solids with many faces.

**Remote use**
- **SSH mode (recommended for a home server):** MCP over `ssh`, one `authorized_keys` line per
  machine pins the key to the MCP server and its own workspace (`restrict`, forced command).
  `b123d-print setup-ssh` writes the line and the client config; `b123d-print pull` fetches
  exported files; a build limit shared by all sessions.
- **HTTP mode (many agents, evals):** Streamable HTTP with **named tokens** (`b123d-print-mcp token
  add|list|revoke`, each limited to its workspaces, logged by name), per-client workspaces, a
  server-wide build limit, health check, graceful shutdown.
- **Exported files over HTTP** come back as signed, expiring download links (no token, no SSH)
  and as `b123d-print://files/` resources.
- **Docker:** a two-container setup for HTTP — the worker that runs part scripts has no network
  at all; `deploy/compose.yaml` example.

**Checks and design rules**
- Sourced FDM best practices (`docs/BEST_PRACTICES.md`, rule IDs cited by checks and AGENTS.md).
- New checks: thin features (fail below one line width), horizontal holes (teardrop), bridge span
  and one-wall ceilings (`max_bridge`), fillets on bed edges, print-in-place gaps.
- Checks report what they measured; `Wall`/`Probe` can be declared in the assembly frame, so
  flipping a part for printing cannot silently redirect them; a reminder when holes are cut
  with no hole compensation set.
- New calibration prints: `fit_coupon`, `overhang_bridge_coupon`, `hole_coupon` with horizontal
  holes; `b123d-print printer calibrate` stores the results per printer + material.

**Tools**
- `compare`: a part against a reference STL/3MF/STEP (aligned distances, score, deviation view);
  CLI and MCP tool. A repo-only eval harness scores agents against reference parts.
- `export`: `parts=` filter, file count and size, a note when the default formats are used.
- `render_preview`: multi-part builds use `assembly()` or lay parts side by side; image `size=`.
- Optional printer/material profiles (405 printers from OrcaSlicer's library) with a fit check.

**Project**
- Docs site: https://kd5ryn.github.io/b123d-print/ (with drift tests against the code).
- Dependabot and a monthly OrcaSlicer printer-table sync.

## 0.1.0 — 2026-10-17

First release: package + CLI, MCP server (stdio, sandboxed part scripts), print checks (overlap,
overhang, wall, probe), STEP/STL/3MF/PNG export, examples, Docker image, Claude Code plugin.
