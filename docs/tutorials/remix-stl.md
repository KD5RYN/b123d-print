# Remix a downloaded STL

You downloaded an L bracket from a model site. It is nearly right, but you want slots instead
of its two screw holes, so it can be adjusted, and gussets to stiffen the corner. This tutorial
takes it from the download to a checked, exported remix, in Claude Desktop.

!!! note "What is real here"
    Every tool call and result on this page comes from running the bundled server locally
    (stdio), trimmed where marked `...`, with paths shortened to `~/parts`. The pictures are the
    ones the tools returned. The "download" is `l_bracket.stl` from the bundled
    [`remix_bracket` example](../scripts/examples.md) (CC0), standing in for a real one. What you
    and the assistant *say* is paraphrased.

Set up first: the [Quick start](../getting-started/quick-start.md), and ideally your printer
(the [first tutorial](first-bracket.md#2-tell-it-your-printer) shows how). The full reference for
what follows is [Remixing a part](../using/remix.md).

## 1. Check the license before anything else

On the model's page, find the license. **-ND** (no derivatives) forbids a remix: stop there.
**-NC** means no commercial use; **BY** means you credit the author when you share the remix.
Note the URL, the author and the license: the assistant records them in the script.

## 2. Put the file where the server can read it

Attaching the STL to the chat does **not** work: the file goes to the model, not to the
b123d-print server, and the server is what loads it. The file goes into the part's `ref/`
folder inside your workspace, the folder you gave as `--workspace` when you connected the server
(in Claude Desktop: Settings → Developer → Edit Config, the path after `"--workspace"`).

You can just ask. Say *"I want to remix ~/Downloads/l_bracket.stl: slots instead of the two
holes, and add gussets. It's CC0, from <URL>."* The assistant asks the server where the file
goes:

```text
>>> upload_reference(part="l_bracket_slots", filename="l_bracket.stl")
This server runs locally: copy the file to ~/parts/parts/l_bracket_slots/ref/l_bracket.stl (create
the folder if needed; you may do it yourself if you can write files). Then
describe_model('l_bracket_slots', 'l_bracket.stl').
```

Claude Desktop without a file tool cannot copy files itself, so it tells you the folder; copy the STL there in
Finder or Explorer. (Claude Code copies it for you. On a [shared
server](../using/remix.md#get-the-original-onto-the-server) the same call returns a signed
upload link for `curl -fT`, or over SSH a `b123d-print push` command.)

## 3. Inspect it

```text
>>> describe_model(part="l_bracket_slots", file="l_bracket.stl")
{
 "format": "stl",
 "units": "none (STL has no units: read as mm)",
 "triangles": 536,
 "faces_before": 536,
 "faces_after": 134,
 "planar_faces": 8,
 "faceted": {"faces": 126, "area_share": 0.029},
 "size": [50.0, 30.0, 30.0],
 "volume": 10960.56,
 "metadata": {},
 "holes": [
  {"d": 4.5, "axis": [0, 0, 1], "center": [-10.0, -4.0, 2.0], ...},
  {"d": 4.5, "axis": [0, 0, 1], "center": [10.0, -4.0, 2.0], ...},
  {"d": 6.0, "axis": [0, 1, 0], "center": [0.0, 13.0, 20.0], ...}
 ],
 "suggestion": {
  "path": "modify or redraw",
  "why": "mostly flat (8 planar faces, 3% curved): modify for small changes (a hole, a boss, a cut);
          offer a parametric REDRAW if proportions change (longer, wider, another screw size), ..."
 },
 "license_note": "record the source URL, the author and the license in the script's docstring; ..."
}
```

![The original, as describe_model renders it](../images/tutorial_remix_original.png)

50 × 30 × 30 mm is a believable bracket, so the units are right (a 2 mm "bracket" would have
been drawn in inches: `scale="inch"`). The file carries no license metadata, so the assistant
uses what you told it. It found the two 4.5 mm screw holes and their centers, which the remix
needs.

## 4. Agree on the plan

The assistant proposes **MODIFY**: load the mesh as it is and cut and add to it, since the
proportions stay the same. It lists each change as a named dimension and waits:

> | Field | Value | Source |
> | --- | --- | --- |
> | `HOLE_X`, `HOLE_Y` | ±10, −4 mm | the original's holes (describe_model) |
> | `SLOT_W` | 4.5 mm | the original hole, same M4 screw |
> | `SLOT_L` | 10 mm center to center along Y | your adjustment, ±5 mm |
> | `GUSSET_X` | ±20 mm | clear of the slots |
> | `GUSSET_T` | 3 mm | as thick as the walls they stiffen |
> | `GUSSET_H` | 14 mm | up the upright and along the base (45°) |
>
> The 6 mm hole in the upright stays as it is. OK?

You say *"yes"*.

## 5. Modify, build, check

The script loads the original with `import_model` and changes it with the named fields; the
source URL, author and license go in its docstring. (The script is the bundled
[`remix_bracket` example](../scripts/examples.md); read it there.)

```python
def build(d: Dims) -> Part:
    part = import_model(d.REF)                       # "ref/l_bracket.stl", where the file puts it
    w = d.SLOT_W + d.HOLE_COMP
    for x in (-d.HOLE_X, d.HOLE_X):                   # slots over the old holes, as real shapes
        slot = SlotCenterToCenter(d.SLOT_L, w, rotation=90, mode=Mode.PRIVATE)
        part -= Pos(x, d.HOLE_Y, -1) * extrude(slot, d.BASE_T + 2)
    for x in (-d.GUSSET_X, d.GUSSET_X):               # two triangular gussets
        ...
    return part
```

```text
>>> build_part("l_bracket_slots")
{"variants": {"standard": {"parts": {"part": {"x": 50.0, "y": 30.0, "z": 30.0,
  "volume": 11186.41, "solids": 1, "valid": true}}, ...}}}

>>> check("l_bracket_slots")
PASSED

l_bracket_slots [standard]
  [OK  ] import   l_bracket.stl: STL, 50.00 x 30.00 x 30.00 mm, 1 solid(s), 134 faces (from 536
         triangles; 126 faceted curve faces). ...
  [OK  ] valid    part: valid solid
  [OK  ] wall     part (base in front of the slot): min wall 3.75 mm (limit 1.2) at [10.0, -11.25], ...
  [WARN] overhang part: inherited from the original: 11 face(s), 20 mm^2 steeper than 45 deg: ...
         z 22.04..22.35 (plane); ...
  [OK  ] thin     part: nothing thinner than 0.8 mm (1.8 lines)
  [OK  ] holes    part: no round holes
  [OK  ] bed edge part: no fillets on the bed edges
  [OK  ] tip-over part: stable: 30 mm tall on a 30 x 58.3 mm footprint ...
```

The overhang warning is **inherited from the original**: the top of the 6 mm round hole in the
upright, at Z ≈ 22. It was there before the remix, so the assistant reports it and leaves it
alone unless you ask ([inherited findings](../using/remix.md#inherited-findings)). The `wall`
check is one the script adds: the material left between a slot and the base's edge.

## 6. Before and after, and `compare`

`before_after` puts the original and the remix side by side, with a score:

```text
>>> before_after("l_bracket_slots")
reference: 50.00 x 30.00 x 30.00 mm, volume 10960.6 mm^3, area 6516.6 mm^2
candidate: 50.00 x 30.00 x 30.00 mm (aligned: 50.00 x 30.00 x 30.00), volume 11186.6 mm^3, area 6838.3 mm^2
...
score 76.2 / 100 -> FAIL
```

![The original (left) and the remix (right)](../images/tutorial_remix_before_after.png)

`compare` measures the exported remix against the original file directly, here after an
`export` that included `stl`:

```text
>>> compare(reference="parts/l_bracket_slots/ref/l_bracket.stl",
            candidate="parts/l_bracket_slots/out/l_bracket_slots.stl", image=True)
reference: 50.00 x 30.00 x 30.00 mm, volume 10960.6 mm^3, area 6516.6 mm^2
candidate: 50.00 x 30.00 x 30.00 mm (aligned: 50.00 x 30.00 x 30.00), volume 11186.5 mm^3, area 6838.2 mm^2
alignment: axes
bbox diff 0.00 x 0.00 x 0.00 mm; volume +2.06%; area +4.94%
surface distance: mean 0.142 mm, rms 0.650, p99 4.851, Hausdorff 6.982 mm (ref->cand 2.246, cand->ref 6.982)
F-score @ 0.5 mm: 0.931 (precision 0.908, recall 0.956)
  [ok  ] bbox_mm: 0 (limit 0.5)
  [ok  ] volume_rel: 0.02061 (limit 0.03)
  [ok  ] area_rel: 0.04936 (limit 0.05)
  [ok  ] mean_mm: 0.1417 (limit 0.2)
  [FAIL] hausdorff_mm: 6.982 (limit 1)
  [FAIL] fscore: 0.9313 (limit 0.95)
  [ok  ] mirrored: 0 (limit 0)
score 76.2 / 100 -> FAIL
```

![Deviation view: green unchanged, red changed, grey only in the remix](../images/tutorial_remix_compare.png)

A FAIL is what a remix should get: the thresholds ask "is this the same part?", and it is not.
Read the picture instead: green where the remix matches the original, red at the old holes (now
slots), grey for the gussets, which only the remix has. The outside size is unchanged (bbox diff
0). If you [redraw](../using/remix.md) a part instead, `compare` before any change should PASS:
that is how a redraw proves it matches ([comparing parts](../using/compare.md)).

## 7. A fit-test template of the base

The slots are what has to fit, so the assistant offers a [template](../using/templates.md) of
the bottom face: a 1.2 mm plate with the slots, to hold against whatever the bracket screws to.

```text
>>> list_faces("l_bracket_slots", highlight="bottom", size="small")
face 2 in red: parts/l_bracket_slots/out/l_bracket_slots_face2_small.png
...
>>> make_template("l_bracket_slots", kind="face", face="bottom")
Template l_bracket_slots_template_face_bottom (standard, from part): 50.00 x 30.00 x 1.20 mm, valid=True,
1 piece(s), laid with the part's bottom side down (its print orientation)
Label: 'face_bottom' engraved 0.5 mm deep

Checks: PASSED
...
Files:
  parts/l_bracket_slots/out/l_bracket_slots_template_face_bottom.step
  parts/l_bracket_slots/out/l_bracket_slots_template_face_bottom.stl
  parts/l_bracket_slots/out/l_bracket_slots_template_face_bottom.3mf
  ...
```

![Where the template comes from: the base, in red](../images/tutorial_remix_template_where.png)

It prints the way the part does (bottom down), so it checks the slot widths too, not only
their positions.

## 8. Export and bring it home

```text
>>> export("l_bracket_slots", formats="stl,3mf,png")
Exported 5 file(s), 826 KB in all.
[standard]
  part: 50.00 x 30.00 x 30.00 mm, valid=True
  ...
  parts/l_bracket_slots/out/l_bracket_slots.stl
  parts/l_bracket_slots/out/l_bracket_slots.3mf
  parts/l_bracket_slots/out/l_bracket_slots.png
  parts/l_bracket_slots/out/l_bracket_slots_before_after.png
  parts/l_bracket_slots/out/l_bracket_slots_vs_original.png
...
```

Locally the files are already in `~/parts/parts/l_bracket_slots/out/`. On a shared server
(HTTP or SSH) they are not on your machine until the assistant runs
`download_part("l_bracket_slots")` and unzips the result in your project folder, or with
`embed=True` when its shell has no network: the same step as in the [first
tutorial](first-bracket.md#where-the-files-are). The zip holds `ref/l_bracket.stl` too.

Slice the 3MF as usual ([From part to print](../using/slicing.md)).

## 9. Share it with credit

The assistant's report ends with the license and the attribution line to use when you post the
remix, for example:

> Remix of "L bracket" by b123d-print contributors, CC0 1.0, <URL>

For a BY license that credit is required; for -NC, the remix is not for sale either.

## Next

- [Remixing a part](../using/remix.md): import options, units, MODIFY vs REDRAW, all of it.
- [Your first part](first-bracket.md), if you skipped it.
