"""b123d-print: helpers for 3D-printable parts modeled in build123d.

Export (STEP/STL/PNG), previews and cross-sections, print checks (overlap, overhang and bridges, wall
thickness, thin features, holes, bed edges, gaps), fit between pieces (Mates), motion clearance (Motion, Slide), fit-test templates, per-user print settings (hole compensation, clearance), the part-script runner
and import_model (remix an existing STL, 3MF or STEP).
"""

from .checks import (BedEdge, Finding, Fit, Gap, Holes, Overhang, Overlap, Probe, ThinFeature, TipOver, Wall, holes,
                     overhang_faces, overlap, wall_thickness)
from .config import Settings, clearance, hole_comp, load_settings, printer
from .fit import Mates, align_axis, place_on
from .motion import Motion, Slide
from .project import View, run
from .remix import import_model
from .render import export, export_files, render, report, section, section_view
from .templates import Template, crop_template, face_template, list_faces, slice_template

__all__ = [
    "BedEdge", "Finding", "Fit", "Gap", "Holes", "Mates", "Motion", "Overhang", "Overlap", "Probe", "Settings", "Slide", "Template", "ThinFeature", "TipOver", "View",
    "Wall", "align_axis", "clearance", "crop_template", "export", "export_files", "face_template", "hole_comp", "holes", "import_model", "list_faces", "load_settings", "overhang_faces", "overlap", "place_on", "printer", "render", "report",
    "run", "section", "section_view", "slice_template", "wall_thickness",
]
