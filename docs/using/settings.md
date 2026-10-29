# Settings

Settings come from four layers; later ones win:

1. built-in defaults;
2. your **user config**, `~/.config/b123d-print/config.toml` (or `$XDG_CONFIG_HOME/b123d-print/config.toml`);
3. the **workspace config**, the nearest `b123d-print.toml` at or above the part script (or the
   current folder);
4. **environment variables**.

`b123d-print config` shows the settings in effect and which files were found; over MCP,
`list_parts` does. Printer-specific values (`hole_comp`, `printer`, `material`) belong in the
user config, or measured per printer in `calibration.toml` or a workspace's `[calibration]`
tables (below); the workspace config is for values that belong to the project.

!!! warning "Hole compensation"
    Holes are drawn true to size; hole shrinkage is set in your slicer (X-Y hole
    compensation, from the [hole coupon](hole-compensation.md)). Turning on `hole_comp` bakes
    the correction into the files for one printer, with the slicer's hole compensation then at 0.

```toml
# ~/.config/b123d-print/config.toml
[print]
hole_comp = 0        # opt-in: mm built into hole diameters (0: the slicer corrects holes)
hole_comp_h = 0      # the same for horizontal holes (default: hole_comp)
clearance = 0.2      # per side, sliding fit (the default)
press_fit = 0.05     # per side, pressed together
free_fit = 0.3       # per side, turns or moves freely
pip_clearance = 0.3  # between parts printed in place
min_wall = 0.8       # Wall checks fail below this unless they set their own limit
max_overhang = 45    # degrees from vertical
max_bridge = 10      # mm; longer bridges warn
max_triangles = 50000  # import_model refuses bigger meshes
formats = ["step", "stl", "3mf", "png"]
style = "functional"   # design review style for parts without STYLE
review = "warn"        # export and the design review: warn, required or off
filament_price = 25    # per kg: design_metrics shows a cost
print_flow = 10        # mm^3/s for the rough print-time estimate
tip_speed = 200        # mm/s: the tip-over check scales with it; 0 turns it off
```

## Keys

Keys go under `[print]` or `[workspace]` (the template puts `parts_dir` under `[workspace]`).
An unknown key is an error, so typos don't pass silently.

| Key | Default | What it does |
| --- | --- | --- |
| `hole_comp` | `0.0` | opt-in: mm built into every hole diameter when cutting, for one printer (then the slicer's X-Y hole compensation stays 0). By default holes are true to size and the slicer corrects them; see [Hole compensation](hole-compensation.md) |
| `hole_comp_h` | same as `hole_comp` | the same for horizontal holes (axis in XY): `hole_comp(__file__, horizontal=True)` |
| `clearance` | `0.2` | mm per side between mating parts that slide, the default fit; part scripts read it with `clearance(__file__)` |
| `press_fit` | `0.05` | mm per side for parts pressed together |
| `free_fit` | `0.3` | mm per side for parts that turn or move freely |
| `pip_clearance` | `0.3` | mm between parts printed in place; the gap check fails below it |
| `min_wall` | `0.8` | Wall checks fail below this (mm) unless a check sets its own `min`; the thin check warns below it |
| `max_overhang` | `45` | degrees from vertical; steeper downward faces are reported |
| `max_bridge` | `10` | mm; longer bridges warn |
| `max_triangles` | `50000` | [`import_model`](remix.md) refuses meshes with more triangles (simplify them first); measured: a 56k-triangle original takes about a minute to check |
| `printer` | `""` (generic) | optional [printer profile](printer-profiles.md) |
| `material` | `""` | optional material profile: `pla`, `petg`, `asa`, `abs`, `tpu` or your own |
| `formats` | `step`, `stl`, `3mf`, `png` | what export writes: `step`, `stl`, `3mf`, `png`, `glb`, `print`, `hardware` ([formats](formats.md)) |
| `style` | `""` (functional) | the [design review](design-review.md) style for parts whose script sets no `STYLE`: `functional`, `modern`, `least_cost`, `rugged`, `soft`, `structural`, `organic` or [your own](design-review.md#custom-styles) |
| `review` | `"warn"` | what `export` does when the [design steps](design-review.md#the-review-checklist) (a passing check, preview and section, `design_metrics`, `suggest_orientation`, a style) did not run on this version of the part: `warn` exports and says what was skipped (in the result and on the print sheet), `required` refuses unless called with `skip_review="<the user's reason>"` (recorded on the print sheet), `off` says nothing and ends no result with the checklist |
| `filament_price` | none | price per kg of filament; `design_metrics` then shows a cost next to the filament estimate |
| `print_flow` | `10` | mm³/s the printer sustains, for `design_metrics`' rough print-time estimate (standard hotend 8-12, high-flow 20 and more) |
| `tip_speed` | `200` | mm/s, your slicer's fastest print move (infill or inner walls); the [tip-over check](checks.md) estimates the brim OrcaSlicer's Auto brim would give at this speed and warns from 5 mm; `0` turns the check off |
| `supports` | `""` (from the geometry) | your support style for the [print sheet](slicing.md#the-print-sheet): `none`, `auto`, `build_plate_only` or `tree`; a part's [`PRINT`](../scripts/convention.md#print-intent) wins. It changes the advice only, not the checks |
| `walls` | `0` (the slicer default, 2) | your wall count (perimeters) for the print sheet and the filament and time estimates; a part's `PRINT` wins |
| `infill` | none (15) | your infill percent for the print sheet and the estimates; a part's `PRINT` wins |
| `parts_dir` | `"parts"` | folder in the workspace that holds `<name>/<name>.py` |

All clearances are per side. Part scripts read any of them with `load_settings(__file__)`, e.g.
`FREE_FIT: float = load_settings(__file__).free_fit`. The [fit coupon](../scripts/examples.md#fit_coupon)
measures the fits and the [overhang/bridge coupon](../scripts/examples.md#overhang_bridge_coupon)
the limits.

With a printer set, `min_wall`, `max_overhang` and `max_bridge` come from the printer, then the
values you measured for that printer + material (`hole_comp`, `hole_comp_h`, the fits,
`max_overhang`, `max_bridge`; stored with `b123d-print printer calibrate`) replace the user
config's, unless the workspace config or the environment sets them; a material's `clearance`
replaces the default the same way.

## Calibration and printer nicknames

Two more tables can go in the user config or the workspace config:

```toml
[printers]                      # nicknames, for two printers of the same model
p2s-garage = "bambu_lab_p2s"

[calibration."p2s-garage/pla"]  # workspace config only: measured values per printer + material
hole_comp = 0.3
```

`printer` may then be a nickname: the profile behind it gives the bed and nozzle, and the
measured values are looked up under the nickname. The measured values for the active printer
come from, later wins:

1. `~/.config/b123d-print/calibration.toml` (`b123d-print printer calibrate`);
2. the workspace config's `[calibration."<printer>/<material>"]` tables (`printer calibrate
   --workspace`, or `save_setup` on a shared server).

In both, a key missing for the material falls back to `"<printer>/any"`. A flat value under
`[print]` in the workspace config, or an environment variable, still wins over both. See
[Printer profiles](printer-profiles.md#two-printers-of-the-same-model).

## Environment variables

| Variable | Does |
| --- | --- |
| `B123D_PRINT_HOLE_COMP` | overrides `hole_comp` |
| `B123D_PRINT_HOLE_COMP_H` | overrides `hole_comp_h` |
| `B123D_PRINT_CLEARANCE` | overrides `clearance` |
| `B123D_PRINT_PRESS_FIT` | overrides `press_fit` |
| `B123D_PRINT_FREE_FIT` | overrides `free_fit` |
| `B123D_PRINT_PIP_CLEARANCE` | overrides `pip_clearance` |
| `B123D_PRINT_MIN_WALL` | overrides `min_wall` |
| `B123D_PRINT_MAX_OVERHANG` | overrides `max_overhang` |
| `B123D_PRINT_MAX_BRIDGE` | overrides `max_bridge` |
| `B123D_PRINT_MAX_TRIANGLES` | overrides `max_triangles` |
| `B123D_PRINT_FORMATS` | overrides `formats`, e.g. `step,3mf` |
| `B123D_PRINT_PRINTER` | overrides `printer` |
| `B123D_PRINT_REVIEW` | overrides `review` (`warn`, `required`, `off`): a shared server's operator can require the design review in every workspace |
| `B123D_PRINT_WORKSPACE` | the MCP server's workspace when `--workspace` is not given |
| `B123D_PRINT_TIMEOUT` | the MCP server's per-build time limit in seconds when `--timeout` is not given (default 240) |
| `B123D_PRINT_NO_CACHE` | `1` turns the MCP server's [build cache](../scripts/convention.md#big-and-multi-piece-projects) off: every call builds the part again |
| `B123D_PRINT_CHECK_TIMEOUT` | the MCP server's time limit for a `check` call in seconds when `--check-timeout` is not given (default 300, or the build limit if that is longer) |
| `B123D_PRINT_MAX_BUILDS` | the MCP server's `--max-builds`; also holds across all server processes of the user (one per SSH connection) |
| `B123D_PRINT_MAX_MEMORY` | the MCP server's (and worker's) `--max-memory`: memory per build process, e.g. `2g` (default); `0` = no limit |
| `B123D_PRINT_QUICK_SLOTS` | the MCP server's `--quick-slots`: build slots kept for quick calls |
| `B123D_PRINT_CLIENT_JOBS` | the MCP server's `--client-jobs`: calls per HTTP client running and waiting (default 4) |
| `B123D_PRINT_MAX_UPLOADS` | the MCP server's `--max-uploads`: signed-link uploads at once, all HTTP clients together (default 8) |
| `B123D_PRINT_CLIENT_UPLOADS` | the MCP server's `--client-uploads`: signed-link uploads at once per HTTP client (default 2) |
| `B123D_PRINT_TRANSPORT` | the MCP server's `--transport` (`stdio` or `http`) |
| `B123D_PRINT_HOST` | the MCP server's `--host` (HTTP; the Docker image sets `0.0.0.0`) |
| `B123D_PRINT_PORT` | the MCP server's `--port` (HTTP) |
| `B123D_PRINT_ALLOWED_HOSTS` | the MCP server's `--allowed-hosts` (HTTP) |
| `B123D_PRINT_SHUTDOWN_GRACE` | the MCP server's `--shutdown-grace` (HTTP) |
| `B123D_PRINT_PUBLIC_URL` | the MCP server's `--public-url` (HTTP download links) |
| `B123D_PRINT_LINK_TTL` | the MCP server's `--link-ttl` (HTTP download links) |
| `B123D_PRINT_RETENTION_DAYS` | the MCP server's `--retention-days`: a named HTTP workspace nobody used for this many days is [removed](../getting-started/http.md#workspace-retention) (default 30; `0` = never) |
| `B123D_PRINT_LINK_SECRET` | key that signs download links; default: derived from `B123D_PRINT_TOKEN`, so changing the token also invalidates old links |
| `B123D_PRINT_TOKENS_FILE` | the MCP server's `--tokens-file`: [named tokens](../getting-started/http.md#tokens) (HTTP) |
| `B123D_PRINT_JOB_QUEUE` | the MCP server's `--job-queue`: builds go to a separate `worker` (HTTP) |
| `B123D_PRINT_TOKEN` | the bearer token HTTP clients must send ([Over the network](../getting-started/http.md)) |
| `B123D_PRINT_TOKEN_FILE` | path of a file holding that token, instead of `B123D_PRINT_TOKEN` |
| `B123D_PRINT_SANDBOX` | `none` turns the OS [sandbox](sandbox.md) off (the Docker image does; the container is the sandbox) |
| `B123D_PRINT_CONFIG_IN_WORKSPACE` | `1` keeps the user config in `<workspace>/.config/` (set in the Docker image, whose home folder does not last) |

A generated table of the keys with the comments from the code is in the
[Reference](../reference.md#settings).
