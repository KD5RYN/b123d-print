# Third-party software and credits

b123d-print is a thin layer over other people's work. It does **not** copy or bundle their code:
they are installed as dependencies, under their own licenses. Versions are the ones pinned in
`pyproject.toml` / `uv.lock`.

| Project | Used for | License |
| --- | --- | --- |
| [build123d](https://github.com/gumyr/build123d) 0.13.0 | the CAD modeling API every part script is written in | Apache-2.0 |
| [OCP](https://github.com/CadQuery/OCP) (`cadquery-ocp-novtk` 8.0.1) | Python bindings to OpenCascade, used by build123d | Apache-2.0 (bindings) |
| [Open CASCADE Technology](https://dev.opencascade.org) 8.0.x (shared libraries inside the OCP wheel) | the geometry kernel: solids, booleans, sections, STEP/STL | LGPL-2.1 with the OCCT exception |
| [matplotlib](https://matplotlib.org) 3.11 | preview renders and cross-section images | Matplotlib license (PSF-based) |
| [NumPy](https://numpy.org) 2.5 | tessellation math in the checks | BSD-3-Clause (and bundled 0BSD, MIT, Zlib, CC0) |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 2.3 | the MCP server | MIT |
| [uv](https://github.com/astral-sh/uv) | install / run (`uvx`), build backend `uv_build` | Apache-2.0 or MIT |
| [lib3mf](https://github.com/3MFConsortium/lib3mf) (via build123d) | 3MF export | BSD |
| [bd_warehouse](https://github.com/gumyr/bd_warehouse) 0.4.0 | threads, fasteners and their hole sizes, heat-set inserts, gears, V-slot parts for part scripts | Apache-2.0 |
| [py_gearworks](https://github.com/GarryBGoode/py_gearworks) 0.0.24 | involute gears for part scripts | Apache-2.0 |
| [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) printer profiles | source of the printer table (`data/printers_orca.json`) | AGPL-3.0 — see below |

build123d also pulls in ocpsvg (Apache-2.0), ocp-gordon (Apache-2.0),
ezdxf (MIT), sympy (BSD), scipy (BSD), anytree (Apache-2.0), svgpathtools (MIT) and others;
`uv pip list` shows the full set and each package's metadata carries its license.

## Notes for redistribution

- **Python package (wheel/sdist):** contains only b123d-print's own code (MIT). Dependencies are
  fetched from PyPI by the installer, so no third-party license texts need to ship with it.
- **Docker image:** the image *does* contain the dependencies, including the OpenCascade shared
  libraries (LGPL-2.1). Anyone publishing the image should keep the license files that come with
  each installed package (they are in each `*.dist-info/` folder, left in place by the
  Dockerfile) and point to the OCCT source (https://github.com/Open-Cascade-SAS/OCCT); LGPL
  lets users replace the library, which a pip-installable stack already allows.
- **Printer table:** `src/b123d_print/data/printers_orca.json` holds only facts (model name,
  build volume, bed shape, nozzle size) read from OrcaSlicer's printer profiles by
  `tools/sync_orca_printers.py`; the OrcaSlicer commit is recorded in the file. No OrcaSlicer
  files, text or code are included. Thanks to the OrcaSlicer project and the printer makers who
  maintain those profiles.
- **Example parts** in `src/b123d_print/examples/` are original designs, MIT like the rest. Some
  call bd_warehouse or py_gearworks at build time; they copy no code from them.
- **bd_warehouse and py_gearworks** (Apache-2.0) are dependencies, not bundled: they ship no
  NOTICE file, and the Docker image keeps their license files in `*.dist-info/`, which is what
  Apache-2.0 asks of a redistribution. bd_warehouse's data tables (fastener, insert and thread
  sizes from published standards and makers' datasheets) are read from the installed package.
