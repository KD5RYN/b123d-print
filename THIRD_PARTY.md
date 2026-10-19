# Third-party software and credits

b123d-print is a thin layer over other people's work. Apart from one vendored library, three.js
for the 3D viewer (below), it does **not** copy or bundle their code: they are installed as
dependencies, under their own licenses. Versions are the ones pinned in `pyproject.toml` /
`uv.lock`.

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
| [three.js](https://github.com/mrdoob/three.js) (npm three 0.186.1, **vendored**) | the browser 3D view (`export`'s view link, `b123d-print view`): WebGL rendering, GLTFLoader, OrbitControls | MIT |
| [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) printer profiles | source of the printer table (`data/printers_orca.json`) | AGPL-3.0 — see below |

build123d also pulls in ocpsvg (Apache-2.0), ocp-gordon (Apache-2.0),
ezdxf (MIT), sympy (BSD), scipy (BSD), anytree (Apache-2.0), svgpathtools (MIT) and others;
`uv pip list` shows the full set and each package's metadata carries its license.

## Notes for redistribution

- **Python package (wheel/sdist):** b123d-print's own code (MIT), plus one vendored library:
  three.js (MIT, © 2010-2026 three.js authors), as `src/b123d_print/data/viewer/three.bundle.min.js`.
  It is a minified bundle of three.js's core, GLTFLoader and OrbitControls built by
  `tools/vendor_viewer.py` from the npm tarball (version, integrity hash and the bundle's SHA-256
  in `data/viewer/vendor.json`; GLTFLoader's optional Draco, meshopt and KTX2 decoders are not
  included). The MIT license asks that its notice go with every copy, so: the full license text
  heads the bundle itself, ships next to it as `three-LICENSE.txt`, is listed in `license-files`
  (so wheels carry it in `.dist-info/licenses/`), is linked from the served viewer page, and is
  inside every self-contained view HTML that `b123d-print view` writes (they embed the bundle).
  The viewer's own code (`viewer.js`, `viewer.css`, `viewer.html`) is b123d-print's, MIT. All
  other dependencies are fetched from PyPI by the installer, so their license texts come with them.
- **View HTML files** you share (`*_view.html`): they contain three.js with its license notice
  at the top of the embedded script; keep it there. The model in them is your part, under
  whatever terms you choose (for a remix, the original's license still applies: see
  [Remixing](https://kd5ryn.github.io/b123d-print/using/remix/)).
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
- **Example parts** in `src/b123d_print/examples/` are original designs, MIT like the rest.
