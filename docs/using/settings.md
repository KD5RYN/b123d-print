# Settings

Settings come from four layers; later ones win:

1. built-in defaults;
2. your **user config**, `~/.config/b123d-print/config.toml` (or `$XDG_CONFIG_HOME/b123d-print/config.toml`);
3. the **workspace config**, the nearest `b123d-print.toml` at or above the part script (or the
   current folder);
4. **environment variables**.

`b123d-print config` shows the settings in effect and which files were found; over MCP,
`list_parts` does. Printer-specific values (`hole_comp`, `printer`, `material`) belong in the
user config; the workspace config is for values that belong to the project.

```toml
# ~/.config/b123d-print/config.toml
[print]
hole_comp = 0.4      # mm added to hole diameters when cutting
hole_comp_h = 0.5    # the same for horizontal holes (default: hole_comp)
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
filament_price = 25    # per kg: design_metrics shows a cost
print_flow = 10        # mm^3/s for the rough print-time estimate
tip_speed = 200        # mm/s: the tip-over check scales with it; 0 turns it off
```

## Keys

Keys go under `[print]` or `[workspace]` (the template puts `parts_dir` under `[workspace]`).
An unknown key is an error, so typos don't pass silently.

| Key | Default | What it does |
| --- | --- | --- |
| `hole_comp` | `0.0` | mm added to hole diameters when cutting; see [Hole compensation](hole-compensation.md) |
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
| `formats` | `step`, `stl`, `3mf`, `png` | what export writes: `step`, `stl`, `3mf`, `png`, `glb` ([formats](formats.md)) |
| `style` | `""` (functional) | the [design review](design-review.md) style for parts whose script sets no `STYLE`: `functional`, `modern`, `least_cost`, `rugged`, `soft`, `structural` or [your own](design-review.md#custom-styles) |
| `filament_price` | none | price per kg of filament; `design_metrics` then shows a cost next to the filament estimate |
| `print_flow` | `10` | mm³/s the printer sustains, for `design_metrics`' rough print-time estimate (standard hotend 8-12, high-flow 20 and more) |
| `tip_speed` | `200` | mm/s, your slicer's fastest print move (infill or inner walls); the [tip-over check](checks.md) estimates the brim OrcaSlicer's Auto brim would give at this speed and warns from 5 mm; `0` turns the check off |
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
| `B123D_PRINT_WORKSPACE` | the MCP server's workspace when `--workspace` is not given |
| `B123D_PRINT_TIMEOUT` | the MCP server's per-build time limit in seconds when `--timeout` is not given (default 240) |
| `B123D_PRINT_NO_CACHE` | `1` turns the MCP server's [build cache](../scripts/convention.md#big-and-multi-piece-projects) off: every call builds the part again |
| `B123D_PRINT_CHECK_TIMEOUT` | the MCP server's time limit for a `check` call in seconds when `--check-timeout` is not given (default 300, or the build limit if that is longer) |
| `B123D_PRINT_MAX_BUILDS` | the MCP server's `--max-builds`; also holds across all server processes of the user (one per SSH connection) |
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
