# Measuring for the AI

The assistant can only model what you tell it. A small bracket needs four caliper readings; a
1.5 m trim with curved ends needs a plan. This page is that plan: which tool to measure with,
how to avoid the usual errors, how to photograph a part so the numbers can be read off the
photo, and how to hand it all over so nothing is ambiguous.

The short version:

1. **Pick one datum** (a reference face, edge or line) and measure everything from it.
2. **Give units, and an accuracy for every number** ("62.4 mm, calipers, ±0.05";
   "about 310 mm, tape along the curve, ±5").
3. **Say what must fit what** ("the slot must slide over this 3.0 mm tab").
4. **For large or curved parts, measure a table of offsets**: stations at a fixed spacing, one
   height or width at each.
5. **Put a scale in every photo**, in the same plane as the feature, and shoot it square on.
6. **Test before the full print**: a [fit-test template](templates.md), a 1:1 paper print-out
   of the profile, or one short section.

## Pick the method by part type

| The part | Measure with | Hand over | Check before printing |
| --- | --- | --- | --- |
| **Small and precise** (a bracket, an adapter, a board, under ~150 mm) | calipers (outside, inside, depth, step) | a measurement sheet | a fit-test template of the mating face |
| **Flat outline** (a gasket, a cover plate, a panel cut-out) | flatbed scan at a known DPI, or a photo square on, on a grid or cutting mat | the image with its scale, plus caliper readings of the critical sizes | a 1:1 paper print-out laid on the original |
| **Curved profile** (a handle, a moulding, a pipe bend, a rounded corner) | profile (contour) gauge, radius gauge, bent wire, tracing on paper, or offsets | a traced or scanned outline, or an offsets table, plus the radii you could gauge | the profile printed 1:1 on paper or cut from card |
| **Large** (over ~250 mm, or bigger than the bed) | tape and straightedge or string line from a datum, offsets at stations, a level | an offsets table per surface, overall lengths, diagonals | one short test section, a cardboard template |
| **Mating with something** (a lid, a sleeve over a tube, a mount on a board) | calipers on the *mating feature*, not just the outside | the mating sizes and the fit you want (press, sliding, free) | a [fit-test template](templates.md) of that feature |
| **Organic or very complex** (a car part, a figure, a knob with grip ridges) | photogrammetry or a phone 3D scan for the shape, calipers for the sizes that matter | the scan as a reference model ([remix](remix.md)) plus caliper readings | a test section of the critical area |

Mix them: a large trim is offsets for the long run, a profile gauge for its cross-section and
calipers for the clip that holds it.

## Datums, accuracy and how many digits

- **A datum is the one place you measure from**: a flat bottom, a straight edge, the centre of a
  main hole, a string pulled tight along a large part. Name it ("all heights from the floor",
  "X from the left end of the trim, Y from the top edge").
- **Measure every point from the datum; don't chain.** Ten 50 mm steps each read ±0.5 mm can
  add up to ±5 mm at the end; ten readings from the datum are each still ±0.5 mm. This is the
  same reason drawings use baseline dimensioning instead of chained dimensions.
- **Give the accuracy you actually have**, not the display's digits. A caliper shows 0.01 mm but
  your reading of a soft or rounded edge may be good to 0.1; a tape along a curve may be good to
  5 mm. Write it down: the assistant uses it to decide where clearance or adjustment is needed.
- **How many digits matter**: a well-tuned printer is good to about 0.2 mm on small features
  (Prusa); a print service quotes desktop FDM at ±0.5 %, no better than ±0.5 mm (Protolabs), and
  plastics shrink as they cool (PLA ~0.35 %, ABS/ASA ~0.7 %, CNC Kitchen). So 0.1 mm is plenty for
  anything printed; give 0.05 only for the mating sizes you measured with calipers. Over 100 mm,
  0.5 mm is usually enough.
- **Measure three times and average** anything that matters, from slightly different places
  (CNC Kitchen does this even for calibration prints; NIST calls the spread of repeated
  readings a Type A uncertainty).
  If the three readings disagree by more than your accuracy, the part isn't the shape you
  think (tapered, oval, warped): say so.
- **Mark each value CONFIRMED or estimated.** "Confirmed" means measured, ideally twice;
  "estimated" means read from a photo, assumed from a standard, or guessed. The assistant asks
  about the estimated ones that matter.

## Taking each kind of measurement

### Calipers

A caliper has four ways to measure: the big **outside jaws**, the small **inside jaws** (for
holes and slots), the **depth rod** out of the end, and the **step** (the end of the sliding jaw
against the end of the body, for a step height).

- **Zero it** with the outside jaws closed and clean, every time you pick it up (Mitutoyo
  specifies a caliper's accuracy with the zero set on the outside faces).
- **Measure close to the beam.** Use the part of the jaws nearest the scale, not the tips: any
  play in the slide tips the jaw, and the error grows with the distance from the beam (Abbe
  error; a micrometer avoids it, a caliper can't). Gentle, even pressure, the same every time
  (the thumb wheel helps); hold the jaws parallel to the part. Pressure is the caliper's biggest
  source of scatter.
- **Holes**: inside jaws in the hole, then rock them gently and read the **largest** value
  (otherwise you measure a chord, which is smaller). Turn 90° and measure again: a printed or
  worn hole is often oval. For small holes, use the shank of a drill bit that just fits, then
  measure the bit.
- **Depth**: keep the end of the caliper flat on the top face; the rod must be square to it.
- **Thin or soft parts** (rubber, foam, thin plastic): close the jaws until they just touch;
  pressure squashes them.
- **Distance between holes**: measure edge to edge (outside of both, then inside of both) and
  take the average; that is the centre-to-centre distance without guessing where a centre is.
  The same trick on a printed part (an outside and an inside size, averaged) cancels over- or
  under-extrusion.

### Tape measures and rules

- **The hook slides on purpose**: it moves by its own thickness so a push (inside) and a pull
  (outside) measurement both start at the true zero. A bent or worn hook is a 1–2 mm error.
- **"Burn an inch"** (or 10 cm) for anything precise: start at the 1 in or 10 cm mark instead of
  the hook, and subtract it. Write the subtraction down; it is easy to forget.
- **Tape on a slope or around a curve**: say which you measured: **level** (horizontal, with a
  level or along the floor), **straight** (the chord, tape pulled tight between two points) or
  **along the surface**. A single number from a tape running uphill along a curved part is
  ambiguous; it took a full re-measure to fix on one real project.
- **Steel rules** are better than tapes under ~300 mm: stand the rule on edge so the marks touch
  the part, and read straight down (no parallax).
- **Mixed units**: if your tape reads inches and your calipers read mm, say so per value. The
  assistant works in mm and should confirm every converted number with you.

### Gauges

- **Profile (contour) gauge**: press it square into the shape, lock it, then trace it on paper
  or photograph it flat on a grid. Long shapes: take overlapping sections and mark the overlap.
- **Radius (fillet) gauges**: try leaves until one sits with no light under it; the leaf's number
  is the radius. Good for rounded corners and inside fillets you can't caliper.
- **Feeler gauges**: for gaps and thin clearances (how much play a lid has, how wide a slot is).
- **Thread pitch gauge**: find the leaf that seats with no rocking; measure the outside diameter
  with calipers. M3 vs 4-40, M6 vs 1/4-20 look alike; the gauge tells them apart.

### Curves: wire, tracing, rubbings

- **Bent wire or solder**: bend a stiff wire (or a length of solder, or a "flexible curve"
  drawing tool) to the curve, lift it off without opening it, lay it on paper and trace it. Mark
  where the curve starts and ends, and add two tape readings across it (its height and length)
  as a check on the tracing.
- **Tracing**: lay paper on or against the part and trace with a pencil held vertical. For a
  hole pattern, a **rubbing** (paper over the face, rub with a pencil's side) shows the holes and
  edges at 1:1.
- **Hand it over** as a scan or a square-on photo of the tracing with a ruler on the paper, plus
  the two check numbers. The assistant can fit a curve to it (an arc, a spline, a superellipse)
  and give you back the parameters to confirm.

### Offsets: the table of offsets

Boat builders describe a curved hull with a **table of offsets**: stations (cross-sections) at
a fixed spacing along a baseline, and at each station a few distances measured from the
baseline. It works for any long or curved part.

1. **Lay a datum line**: a straightedge, a long level, a chalk line or a string pulled tight
   along the part (or the floor, if the part stands on it).
2. **Mark stations** at a fixed spacing along it: every 50 mm on a 500 mm part, every 100 mm on a
   1.5 m one; closer where the shape changes fast (a curved end), wider on straight runs.
3. **At each station, measure square to the datum** (use a square or a level) the offsets you
   need: the height of the top edge, the depth to the surface, the width.
4. **Write it as a table**, one row per station (template [below](#table-of-offsets-template)).
   Note where each feature starts and ends (a clip, a bend, the end of a straight run).
5. **Check it**: measure the overall length and, for anything that should be square, the two
   **diagonals** (equal diagonals = square corners).

The assistant turns the table into a spline or fits a simple curve, and you check the result
against the part before printing (see [Verify before the full print](#verify-before-the-full-print)).

### Large parts

- **Split it into sections** that fit the bed, and measure each section's ends where they will
  join. Tell the assistant where you want the joints (a straight run is easiest).
- **Heights from one reference**: the floor, a straightedge, a level line or a string. Use a level
  to make the reference level, or measure its slope once and say so.
- **Distances along a curve vs straight**: give the straight distance (chord) and, separately,
  the length along the surface if it matters (a trim that must cover a curved edge).
- **Check square with diagonals**, or with 3-4-5: 300 mm along one side, 400 mm along the other,
  500 mm between the marks (scale it up for long sides: 600-800-1000; keep the tape taut).
- **Make a cardboard template** of the outline from your numbers before printing anything (see
  below): it catches a wrong reading in minutes.

### 3D scans and photogrammetry

- **Phone LiDAR / "3D scanner" apps** capture the overall shape quickly, but published tests
  of five iOS apps on a corridor and a street found errors of about 1 cm in some areas and
  about 10 cm in others. Good for a reference
  shape, not for a fit.
- **Photogrammetry** (many overlapping photos, processed into a mesh) comes out at an arbitrary
  scale: it is only as good as the reference you put in the scene. Include a ruler, or two
  markers at a distance you measured with calipers, and say what it is. A calibrated desktop
  scanner can be far better (CNC Kitchen measured one within 0.03 mm over 100 mm), but check it
  the same way: scan something you measured.
- Either way, give the assistant the mesh as a reference model ([remix](remix.md):
  `upload_reference`, `describe_model`) **and** caliper readings of the sizes that must fit. The
  calipers win where they disagree.

## Photographing for the AI

A photo carries the shape and the intent; with a scale in it, it can also carry approximate
sizes. Typed numbers always win over sizes read from a photo.

- **Square on**: point the camera straight at the face you want measured, centred on it. A
  tilted camera makes the near side bigger than the far side (perspective).
- **From farther away, zoomed in**: stand back and use the 2× or 3× lens rather than the wide
  one up close. The wide lens bends straight lines near the edges (barrel distortion) and
  exaggerates perspective; distance flattens both. Keep the feature in the middle of the frame.
- **Scale in the same plane** as the feature: a ruler, a yardstick, a tape, a printed grid or a
  cutting mat, laid on or held against the face you are measuring. A scale that sits closer to
  or farther from the camera than the feature (parallax) is read at the wrong size. Small
  objects: a coin or a **credit card** (ISO/IEC 7810 ID-1: 85.60 × 53.98 mm) work if nothing
  else is at hand.
- **Good, even light**: daylight or two lamps; no hard shadows on the edges you want read, no
  flash glare on shiny parts.
- **One feature per photo**, and name the photos ("photo 3: left end, from the front, ruler at
  the bottom edge"). An overview photo first, then the close-ups.
- **Show the calipers in the photo** when you read them: the assistant sees which feature each
  number belongs to.
- **Flat parts on a flatbed scanner**: a scanner gives true scale at its DPI (at 300 DPI, 1 mm
  is 11.8 pixels) with no perspective. Scan with a ruler or a card on the glass anyway: the DPI
  in the file is not always right. Parts
  thicker than a few mm blur and grow at the edges: scan the face that lies on the glass.
  The assistant can [trace the outline](tracing.md) from the scan (or from a photo on a grid)
  instead of you measuring it point by point.
- **Printing a grid or a scan back at 1:1**: print at **100 % / "actual size"**, never "fit to
  page", and measure a known distance on the print with a ruler before you trust it.

## Handing it to the AI

### Measurement sheet template

Copy this into your message, or better into a `MEASURE.md` file next to the part script
(`parts/<name>/MEASURE.md`) so it is the source of truth across sessions; tell the assistant to
read it. Change it there when you re-measure, and the assistant updates the script's dimensions
from it.

```markdown
# <part name>: measurements

- **Units:** mm (tape readings in inches are marked "in")
- **Datum:** <the face, edge or line every value is measured from>
- **Orientation:** <which way is up in use; which face will lie on the bed if you know>
- **Must fit:** <what this part mates with, and the fit: press / sliding / free>
- **Photos:** <photo 1: overview, ruler along the bottom edge; photo 2: ...>

| Feature | Value | Method | Accuracy | Status |
| --- | --- | --- | --- | --- |
| Overall length | 182.4 | calipers, from datum A | ±0.1 | CONFIRMED |
| Mounting hole Ø | 4.2 | calipers, inside jaws, rocked, 2 directions | ±0.05 | CONFIRMED |
| Hole spacing (centre to centre) | 160.0 | calipers, outside + inside edges averaged | ±0.1 | CONFIRMED |
| Top edge radius | 6 | radius gauge | ±0.5 | CONFIRMED |
| Depth of the recess | ~12 | read from photo 3 against the ruler | ±2 | estimated |
```

### Table of offsets template

```markdown
## Offsets: <surface>

- **Datum line:** <e.g. a string pulled tight along the bottom edge, level>
- **Stations:** every <100> mm from <the left end>, X = distance along the datum
- **Measured:** square to the datum, with <a square / a level>; <level / along the surface>
- **Accuracy:** ±<2> mm

| Station | X (mm) | Height above datum | Depth from face | Notes |
| --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 22 | left end, square cut |
| 1 | 100 | 38 | 22 | |
| 2 | 200 | 52 | 23 | clip centre at X = 230 |
| ... | | | | |
```

### Tips

- **Units first**, and per value where they are mixed. The assistant should repeat every
  converted value back to you in mm.
- **Name the datum**, and use the same one in the sheet, the photos and the offsets.
- **An accuracy for each value.** "Good to ~15 mm" is a useful number: it tells the assistant
  that feature needs adjustment room, not a tight fit.
- **Say what must fit what** and how (press, sliding, free): that decides the clearance, not the
  measurement.
- **Say what you couldn't measure.** A missing number the assistant asks about beats one it
  guesses.
- The assistant puts every confirmed value into the part script as a named dimension with a
  comment on its source and accuracy, so you can change one later without re-measuring the rest.

## Verify before the full print

- **A fit-test template** ([Fit-test templates](templates.md)): a 1.2 mm slice of the real
  part's mounting face, a crop of its clip, minutes to print. It checks the hole pattern and the
  fits you measured.
- **A 1:1 paper print-out** of a profile or outline: ask the assistant to export the profile as a
  1:1 SVG (build123d writes one with `ExportSVG`; the section PNGs are not to scale), or open the
  STEP in other CAD and print a 1:1 drawing. Print at 100 %, check a ruler distance on the print,
  then lay it on the part. Glue it to card and cut it
  out for a template you can hold against a curve.
- **One test section** of a large part: a short piece of the straight run and one curved end,
  printed at full size. If they fit, the rest will; if they don't, you changed a few numbers
  instead of reprinting the whole thing.

## Worked examples

### A small bracket

A bracket that clips onto a 25.0 mm tube and takes two M4 screws.

- Datum: the tube's axis and the wall it is mounted on.
- Calipers: tube Ø 25.0 (3 readings, ±0.05, CONFIRMED); screw hole spacing 40.0 (edge to edge
  averaged, ±0.1, CONFIRMED); distance from wall to tube axis 31 (calipers depth rod to the tube,
  plus half Ø, ±0.2, CONFIRMED).
- Must fit: the tube, sliding fit; M4 screws through.
- Check: a fit-test template of the clamp ring (a 1.2 mm slice) to try on the tube.

### A flat cover plate with an odd outline

- Scan the old plate on a flatbed at 300 DPI with a steel rule on the glass; give the scan and
  its DPI.
- Calipers on the screw holes (Ø and spacing) and the plate's thickness.
- The assistant traces the outline from the scan, scales it from the DPI, and checks the scale
  against the rule. Print the outline 1:1 on paper and lay it on the opening before printing.

### A large curved trim, measured as offsets

A trim strip about 1.5 m long that covers the edge of a curved opening: a long gently curving
run with a tighter curve at each end. Loose tape readings and photos were not enough: a tape
run along the curve gave different numbers depending on whether it was read level or along
the surface, and the ends had no clear size. What worked:

1. **Datum**: a straightedge clamped level along the bottom of the opening, one end marked as
   X = 0. Every height is measured straight up from it, with a small square.
2. **Stations every 100 mm** along the straight run, every 25 mm through the curved ends. At each
   station: the height of the edge above the datum and the depth of the lip. A yardstick lay along
   the datum in every photo, so the assistant could read the station marks.
3. **The curved ends**: a bent wire pressed into each curve and traced on paper, with two tape
   readings across it as a check (height and length of the curve). The assistant fitted the
   tracing as a superellipse, |x/a|ⁿ + |y/b|ⁿ = 1, 6.0 in tall × 8.2 in long with n = 1.4, and
   gave the fit back to confirm against the wire.
4. **Units**: the tape read inches, the calipers mm; every converted value was confirmed in mm.
5. **Status and accuracy for each value**: the lip depth CONFIRMED with calipers (±0.1); the
   station heights CONFIRMED with the square (±2 mm); the curve's length estimated from the wire,
   "good to ~15 mm", so the design gave the ends room to trim.
6. **Test before printing**: the part was split into bed-sized sections at the straight run;
   a fit-test print of one straight section and one curved end came before the full set.

In the part script, that became named dimensions like:

```python
@dataclass(frozen=True)
class Dims:
    # Offsets measured from a level straightedge at the bottom of the opening (MEASURE.md);
    # stations every 100 mm, ±2 mm, CONFIRMED
    STATION_X: tuple = (0.0, 100.0, 200.0, 300.0)
    EDGE_H: tuple = (0.0, 38.0, 52.0, 61.0)
    # Lip depth, calipers, ±0.1, CONFIRMED
    LIP_D: float = 22.0
    # Curved end: superellipse fitted to a bent-wire tracing, 6.0 x 8.2 in, ±15 mm along the curve, estimated
    END_H: float = 6.0 * 25.4
    END_L: float = 8.2 * 25.4
    END_N: float = 1.4
```

## Sources

The advice above is common workshop practice; these are the sources checked for it. Each
was fetched and read for the claim in its row, except where marked *not fetched*.

| Topic | Source |
| --- | --- |
| Caliper handling (parallel jaws, steady pressure, thumb wheel), repeat three times, outside + inside averaged cancels extrusion error, shrinkage per material | CNC Kitchen, [Calibration cubes are bad](https://www.cnckitchen.com/blog/calibration-cubes-are-bad-this-is-how-you-calibrate-your-3d-printer) |
| Zero set on the outside faces; accuracy checked from near the beam to the jaw tips | Mitutoyo, [Accuracy and calibration of calipers (PDF)](https://www.mitutoyo.com/webfoo/wp-content/uploads/15003A.pdf) |
| Clamping pressure as the caliper's main scatter; temperature; a tool ~10× finer than the tolerance | Xometry, [What is metrology](https://www.xometry.com/resources/blog/metrology/) |
| Abbe's principle: micrometers follow it, calipers don't | Keyence, [Abbe's principle](https://www.keyence.com/ss/products/measure-sys/measurement-selection/basic/abbe-principle.jsp) |
| Caliper scale out of line with the jaws: measure as close to the rail as possible | MMS, [Errors in hand-held measuring instruments](https://www.mmsonline.com/articles/understanding-errors-in-hand-held-measuring-instruments) |
| Inside diameter: rock the jaws for the largest reading | EngineerFix, [How to measure inside diameter](https://engineerfix.com/how-to-measure-inside-diameter-accurately/) |
| Repeated readings as a (Type A) uncertainty | NIST, [Technical Note 1297, section 2](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-2-classification-components-uncertainty) |
| The tape's hook slides by its thickness (true zero inside and out); burning an inch | Art of Manliness, [Tape measure guide](https://www.artofmanliness.com/skills/manly-know-how/tape-measure-guide/); Stanley, [US patent 4,466,194](https://patents.google.com/patent/US4466194A) |
| Radius gauge: hold it to the light, look for gaps | Grant Trebbin, [Using a radius gauge](https://www.grant-trebbin.com/2016/07/using-radius-gauge.html) |
| Feeler gauge: the blade that slides with a slight drag | AIMS Industrial, [Feeler gauge guide](https://aimsindustrial.com.au/collections/feeler-gauge-guide) |
| Flexible curves for tracing | Lee Valley, [Flexible curves](https://www.leevalley.com/en-us/shop/tools/hand-tools/marking-and-measuring/marking-accessories/32536-flexible-curves) (*not fetched*: HTTP 429) |
| Table of offsets: stations at equal spacing, heights above a baseline, half-breadths from the centreline | Off Center Harbor, [Lofting handouts (PDF)](https://offcenterharbor.com/wp-content/uploads/2021/11/Master-Class_Lofting-Handouts.pdf); WoodenBoat, [Laying down](https://skills.woodenboat.com/?p=646) |
| Perspective comes from distance, not the lens; barrel distortion worst at wide angle | Wikipedia, [Perspective distortion](https://en.wikipedia.org/wiki/Perspective_distortion), [Distortion (optics)](https://en.wikipedia.org/wiki/Distortion_%28optics%29) |
| ID-1 card, 85.60 × 53.98 mm | Wikipedia, [ISO/IEC 7810](https://en.wikipedia.org/wiki/ISO/IEC_7810) |
| Flatbed scan at a known DPI, scaled to true size in CAD | [hackaday.io project 53520](https://hackaday.io/project/53520/instructions) |
| Scaling a model to a measured length in the slicer | Prusa, [Measurement tool](https://help.prusa3d.com/article/measurement-tool_399451) |
| Photogrammetry has arbitrary scale; a scanner checked against a caliper-measured ball bar | CNC Kitchen, [10 tips for better 3D scans](https://www.cnckitchen.com/blog/3d-scanning-tips-creality-raptor) |
| Phone LiDAR apps: ~1 cm in some areas, ~10 cm in others | Treccani et al., [ISPRS Archives XLVIII-2-W8-2024, p. 431](https://isprs-archives.copernicus.org/articles/XLVIII-2-W8-2024/431/2024/) |
| Scale bars between markers at a known distance | Agisoft, [Coded targets and scale bars (PDF)](https://www.agisoft.com/pdf/PS_1.1_Tutorial%20%28IL%29%20-%20Coded%20Targes%20and%20Scale%20Bars.pdf) |
| Datums set the origin; positions from datums limit accumulated tolerance | Xometry, [True position tolerance](https://www.xometry.com/resources/machining/true-position-tolerance/) |
| Chain dimensioning sums the tolerances; baseline doesn't | GD&T Basics, [Tolerance stackup](https://www.gdandtbasics.com/tolerance-stackup) |
| FDM accuracy "at least 0.2 mm"; fits from 0.3 mm; no universal value | Prusa, [Modeling with 3D printing in mind](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135) |
| FDM accuracy: desktop ±0.5 % (no better than ±0.5 mm), industrial ±0.25 % | Protolabs, [Desktop and industrial FDM](https://www.protolabs.com/resources/blog/a-brief-look-at-desktop-and-industrial-fdm-3d-printing/) |
| 3-4-5 (scaled up for long sides) and equal diagonals | EngineerFix, [Squaring with 3-4-5](https://engineerfix.com/how-to-square-a-fence-using-the-3-4-5-method/) |
