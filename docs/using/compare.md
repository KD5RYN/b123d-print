# Comparing parts

`compare` measures how close a part is to a reference model: an original you downloaded, a part
you modeled before, or the output of another tool. It works with STL, 3MF and STEP on either
side, and the two may be modeled in different orientations.

```bash
b123d-print compare reference.stl parts/bracket/out/print/bracket.3mf --image deviation.png
```

From an MCP client, the `compare` tool does the same with files inside the workspace (paths
relative to it, e.g. `refs/bracket.stl` and `parts/bracket/out/print/bracket.3mf`).

## What it does

1. **Loads both files.** STL is taken as millimeters; 3MF carries its units (all build items,
   components and transforms are applied); STEP is tessellated at 0.01 mm.
2. **Aligns the candidate to the reference.** It tries every 90-degree orientation (and the
   mirror images) about the bounding-box centers, in the part's own axes and between the
   principal axes of both parts, then refines the best few with ICP (rigid: no scaling). A
   mirror image is only chosen when it fits clearly better; that matters for parts with a
   handedness.
3. **Measures**, from 20,000 points spread evenly over each surface, the exact distance to the
   other surface, in both directions.

## The numbers

| Number | Meaning |
| --- | --- |
| bbox diff | per-axis difference of the bounding-box sizes, after alignment (mm) |
| volume, area | relative difference of the enclosed volume and the surface area |
| mean, rms, p95, p99 | surface distance statistics (mm) |
| Hausdorff | the largest surface distance, either way (mm): a missing hole or boss shows here |
| F-score | at `tol_mm` (0.5 mm): the share of each surface within tolerance of the other, combined |
| score | 0-100: 40 % F-score, 20 % volume, 20 % bounding box, 20 % p99 distance |

A part compared with itself scores 100. A copy scaled up 1 % scores about 95 (volume +3 %);
the same block with a missing 6 mm hole about 81 (Hausdorff 5 mm).

## Pass or fail

It passes when every check holds. Defaults, and the name to override each with
`--threshold name=value` (CLI, repeatable) or `thresholds="name=value,..."` (MCP):

| Name | Default | Check |
| --- | --- | --- |
| `bbox_mm` | 0.5 | largest bounding-box size difference |
| `volume_rel` | 0.03 | volume difference, relative |
| `area_rel` | 0.05 | surface area difference, relative |
| `mean_mm` | 0.2 | mean surface distance |
| `hausdorff_mm` | 1.0 | largest surface distance |
| `fscore_min` | 0.95 | F-score at `tol_mm`, at least |
| `tol_mm` | 0.5 | the distance the F-score counts as matching |
| `score_min` | 0 | overall score, at least (0: not checked) |
| `allow_mirrored` | 0 | 1 accepts a mirror image as a match |

The CLI exits with code 1 when the comparison fails; `--json` prints every number.

## The deviation view

`--image <png>` (CLI) or `image=true` (MCP) renders the reference in six views, colored by the
distance to the candidate: green where it matches, red where it is off by four times `tol_mm`
or more. Grey shows candidate material where the reference has none.

## From Python

```python
from b123d_print.compare import Criteria, compare

r = compare("reference.stl", "parts/bracket/out/print/bracket.3mf", criteria=Criteria(hausdorff_mm=2))
print(r.text())
r.score, r.passed, r.metrics["hausdorff_mm"], r.failures()
```

Either side can also be a build123d shape or a `Mesh` from `load_mesh()`.
