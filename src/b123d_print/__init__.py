"""b123d-print: helpers for 3D-printable parts modeled in build123d.

Export (STEP/STL/PNG), previews and cross-sections, print checks (overlap, overhang and bridges, wall
thickness, thin features, holes, bed edges, gaps), fit between pieces (Mates), motion clearance (Motion, Slide), fit-test templates, per-user print settings (hole compensation, clearance), the part-script runner
and import_model (remix an existing STL, 3MF or STEP).

The names below are imported when first used (PEP 562), so `import b123d_print` (and the MCP
server, which builds nothing itself) does not load build123d, OCP or matplotlib; a part script's
`from b123d_print import Wall` works as always.
"""

import sys
from importlib import import_module
from types import ModuleType

_FROM = {
    "checks": ("BedEdge", "Finding", "Fit", "Gap", "Holes", "Overhang", "Overlap", "Probe", "ThinFeature", "TipOver", "Wall",
               "holes", "overhang_faces", "overlap", "wall_thickness"),
    "config": ("Settings", "clearance", "hole_comp", "load_settings", "printer"),
    "fit": ("Mates",),
    "motion": ("Motion", "Slide"),
    "project": ("View", "run"),
    "remix": ("import_model",),
    "render": ("export", "export_files", "render", "report", "section", "section_view"),
    "templates": ("Template", "crop_template", "face_template", "list_faces", "slice_template"),
}
_WHERE = {name: mod for mod, names in _FROM.items() for name in names}

__all__ = sorted(_WHERE, key=lambda n: (n[0].islower(), n))


def __getattr__(name: str):
    mod = _WHERE.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{mod}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


class _Package(ModuleType):
    """Keeps `b123d_print.render` the function: importing the submodule b123d_print.render would
    otherwise set the package attribute to the module (as the eager imports used to override)."""

    def __setattr__(self, name: str, value) -> None:
        if name in _WHERE and isinstance(value, ModuleType):
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Package
