# Output formats

| File | For |
| --- | --- |
| `<name>.py` (always) | the parametric source: change a `Dims` value, rebuild everything |
| `.step` | editing in other CAD (Fusion, Onshape, FreeCAD, SolidWorks): an exact solid you can push/pull, fillet and cut, without feature history; changes there don't flow back to the script |
| `.stl` | any slicer |
| `.3mf` | slicers that read it (Bambu Studio, OrcaSlicer, PrusaSlicer); keeps units |
| `.png` | 6-view preview, assembly render, section views |

Pick them in your config (`formats = ["3mf", "png"]`, see [Settings](settings.md)), per run
(`b123d-print build --formats step,3mf`), or with `formats=` on the MCP `export` tool. `all`
means all four. Default: all four.

Files go to `parts/<name>/out/`. A variant's files carry its key as a suffix, and section
views carry the plane and position (`plate_2gang_to_1gang_xy2.45.png` is the `XY` section at
Z = 2.45).
