# Design styles and design review (sourced)

The print checks answer "will it print and will it fit". This page describes the next layer:
**after the print checks pass, the AI reviews whether the part is a good design for its purpose
and for a style the user chose**, and reports concrete suggestions. It never changes the part
by itself.

**Status: implemented** (the `design_metrics` tool and `b123d-print metrics`, the
`design_review` prompt, the AGENTS.md step). It defines the styles, the rules behind them (IDs
`DS-*`), the metrics and the review flow. The decisions of the 2026-10-18 review are in
[§9](#9-decisions-review-of-2026-10-18); how to use it is on [Design review](using/design-review.md).

Every source was fetched on 2026-10-18; claims come from the fetched page, PDF or source file,
never from memory. The raw notes (one claim per source, with what each page says) are kept with
the research, outside the repository.

## 1. How to read this

**Validation rule** (as in [BEST_PRACTICES](BEST_PRACTICES.md)): a rule is kept when at least
**two independent publishers** agree. Papers by the same group count as one publisher (Hekkert
2006 and Post, Blijlevens & Hekkert 2016; the two Kong & Lowe papers). Single-source rules are
marked **(1 src)**, are labeled provisional in AGENTS.md and never become a default threshold.

Design is partly taste, so this page separates three kinds of statement:

- **Evidence**: an empirical finding or a maker's documented behavior (a slicer, a datasheet,
  a measured test). It can justify a metric and a threshold.
- **Normative**: a respected designer's or engineer's principle (Rams, Boothroyd–Dewhurst DFA).
  It can justify a rubric question, not a number.
- **Definition (ours)**: what a style *means* in b123d-print. No source can make "industrial"
  mean exposed screws; we define it, say so, and the user picks the style. A definition only
  selects which sourced rules and metrics a style emphasizes.

**Class** (as in BEST_PRACTICES):

- **m: metric.** `design_metrics` computes it from the solid ([§5](#5-design_metrics)).
- **r: rubric.** The AI judges it from renders, sections and metrics during `design_review`.
- **i: info.** Reported as context (a material note, a reference value); no judgment.
- **d: drop.** Considered and rejected; listed so nobody adds it later.

**Nothing here fails a build.** The review produces findings at two levels: **suggest** (worth
changing for the chosen style) and **note** (information, a trade-off). Print checks keep
deciding pass/fail. **Proposed (ours)** marks a threshold the project chose as a starting value;
it is not a sourced number, and it will be tuned as parts are reviewed.

**IDs.** Code cites `DS-G1`, AGENTS.md `[DS-G1]`. The hyphen keeps them apart from the
BEST_PRACTICES IDs (`BP-W1`, `[W1]`) and from `tests/test_rules.py`'s `[A-Z]\d+` pattern; a
second test does the same job for this page.

Source keys are listed under [Sources](#sources).

---

## 2. General rules (every style)

| # | Rule | Evidence (source: claim) | Kind | Class | Proposed behavior |
|---|---|---|---|---|---|
| DS-G1 | **Coherence: a small, consistent vocabulary of edge treatments and radii**, applied the same way to like features. Unity matters most, but some variety is preferred to pure uniformity. | HEK06: unity in variety is a near-universal principle. PBH16: unity and variety both raise appreciation, unity dominates (3 studies). KAR07: consistency of cues is what makes a form recognizable; too much repetition goes stale (brand ranges: analogy). RAMS #8: nothing arbitrary. C77 *(community)*: edge breaks (≤ 0.5 mm) and styling radii (≥ 3 mm) are distinct families. | evidence + normative | **m** + **r** | Metric: edge-treatment shares and distinct radii/chamfer sizes (M7). Rubric: do like edges get like treatment? The thresholds are per style (§4). |
| DS-G2 | **Economy: as little design as possible; features that do several jobs; every separate part justified.** A part must be separate only if it moves, needs another material, or must come apart for assembly/service. | RAMS #10. HEK06: maximum effect for minimum means. DFA-PALNI, DFA-MTU, DFA-ACC, DFMA-CO: the three Boothroyd–Dewhurst questions. | normative | **m** + **r** | Metric: part and solid count, face count (M9). Rubric: could two parts be one print, or one feature do two jobs? |
| DS-G3 | **Fastener economy: few fasteners, few kinds and sizes, standard ones, one tool.** | DFA-PALNI, DFA-MTU, DFA-ACC, DFA-FIC, DFA-WEV (all agree). | normative | **m** + **r** | Metric: hole diameters grouped into fastener-size classes (M9). Suggest when > 2 distinct screw sizes appear. |
| DS-G4 | **Self-locating and foolproof assembly**: lead-in chamfers, keys and bosses locate parts; a part is symmetric, or obviously asymmetric so it cannot go in wrong. | DFA-PALNI, DFA-MTU, DFA-FIC. | normative | **r** | Rubric on assemblies. Not visual symmetry (DS-G8). |
| DS-G5 | **Signifiers: show where to grip, open, press or insert.** A minimal look must not remove a needed cue. | NOR08, NNG-AFF, NNG-H8. DFA-MTU: mark how a snap fit opens. | normative | **r** | Rubric: can a user tell how to open, hold or mount it from the render? |
| DS-G6 | **Honesty: no fake features** (dummy screws, fake vents, decoration pretending to be function). | RAMS #6. SUL (rhetorical, architecture). | normative | **r** | Rubric. |
| DS-G7 | **Symmetry is a style choice, not a universal quality.** Symmetry tracks beauty for abstract patterns; in 3D products continuity weighed about 3× symmetry (1 study); its effect on preference depends on what the buyer values. | JH-ERP, VRL17 (42 students, bottles), CVS10 (422 respondents, conjoint). | evidence | **m** | Metric: mirror symmetry (M8). Used by modern/minimal only. |
| DS-G8 | **Curvature is a style choice.** People prefer curved over angular shapes on average, but the effect is moderate, depends on personality and expertise, and shifts with fashion; angular shapes hold attention longer. | BN06 (n = 14), BPG16 (4 experiments: liking curves, not disliking angles), COT17 (n = 119; marginal for simple shapes), SB09, GMN16 (review), CAR10 (cars over decades). | evidence | **m** | Metric: share of outside edges rounded (M7). Emphasized by soft/handheld and modern; not a general score. |
| DS-G9 | **Never suggest fixed proportions** (golden ratio, 1:1.618 boxes). | MCM10 and SWT16: no robust population preference, large stable individual differences. CAR10: Fechner's result traces to familiarity. DEV *(press)*. | evidence | **r** | Proportions (M1) are reported as numbers only; the review never suggests a ratio. |

### 2.1 Surfaces, seams and splits on FDM

| # | Rule | Evidence | Kind | Class | Proposed behavior |
|---|---|---|---|---|---|
| DS-S1 | **Stair-stepping is worst on shallow slopes.** Cusp height h = layer × \|cos θ\| (θ between the surface normal and the build direction): 0 on vertical walls, maximal on nearly flat slopes; exactly flat faces are fine. Measured roughness peaks near a 10° build angle, at about one layer height. | LIV17 (cusp formula, credits Dolenc & Mäkelä 1994). WAS17 (roughness grows with layer height and shallowness). BUJ19 (PLA, measured Ra). CURVI19 (staircase most pronounced on gentle slopes). | evidence | **m** | Metric: area with visible stepping (M6). Suggest: turn the part, steepen or flatten the face, or variable layer height in the slicer. |
| DS-S2 | **Put visible faces on vertical walls or on flat up-facing tops; supported faces are rough; the bed face is flat and takes the plate's texture.** | MD-XOM and XOM-MINI (one publisher), PL-ORIENT, STR-SURF, HUBS-FDM, HUBS-ORIENT, PRUSA-MODEL, BOOTH17. *Disagree:* Protolabs says face critical features up, Stratasys says orient visible faces vertically; the cusp model (DS-S1) fits both. | evidence | **r** | Rubric: ask which faces show in use; check them against print orientation and supports (M5, M6). |
| DS-S3 | **Seams hide in sharp, preferably concave, vertical corners**; a plain cylinder cannot hide one (rear placement or scarf seams help). Design corollary: give the seam a corner, edge or groove on the hidden side. | PRUSA-SEAM, ORCA-SEAM, OBICO-SEAM, BIGREP-SEAM. Corollary: BIGREP-SEAM and C77-LINE (one case study). | evidence | **m** + **r** | Metric: share of layers whose outer contour has a sharp corner (M10). Suggest a seam groove on the back when it is near 0 and the part has a show side. |
| DS-S4 | **Chamfers keep a constant printable angle; fillets get steeper and overhang near their end.** Fillets look smoother and hide layer transitions. Bed edges: chamfer (BP-O2); a chamfer with a fillet blended off it is a compromise. | BIGREP-FC, PRUSA-MODEL, STARFISH. *Synthesis (no source says it outright):* fillet vertical edges, chamfer edges that face down. | evidence | **m** + **r** | M7 reports which edges are downward-facing fillets; BedEdge already warns on the bed. |
| DS-S5 | **Texture and deliberate lines hide layer lines** (modeled texture, fuzzy skin on side walls, horizontal grooves or reveals), and can make layers part of the look. | STR-SURF, PRUSA-FUZZY, HACKADAY-LINES (Slant 3D), C77-LINE, PRUSA-BLOG. | evidence | **r** | Suggestion for show faces that cannot be oriented well. |
| DS-S6 | **Split lines go on edges, reveals, bevels or the back, never across a smooth show surface**, with pins/dowels or dovetails to align. | SOVOL-SPLIT, BIGREP-SEAM, PRUSA-CUT, BOOTH17. Joints themselves: BP-J1..J5. | evidence | **r** | Rubric on parts that are split. |
| DS-S7 | **Large flat tops can pillow; ironing helps flat up-facing faces only.** | PRUSA-IRON; numbers (top 6–8 layers) from one hobby blog **(1 src)**. | evidence | **i** | Note for large flat show tops; no number adopted. |
| DS-S8 | **Parts to be sanded or painted:** walls ≥ 3 lines, allow for primer thickness on mating faces. | HUBS-POST **(1 src)**. | evidence | **i** | Provisional note when the user says the part will be finished. |
| DS-S9 | **Edge size reads:** below ~0.5 mm an edge still reads crisp; ~3 mm and up reads as a deliberate rounded form. | C77 *(community, practising designers)* **(1 src)**. | evidence | **i** | Used only to name radius families in M7 output (edge break / styling). |

---

## 3. Cost, rugged and handheld rules

### 3.1 Least cost (filament and time)

| # | Rule | Evidence | Kind | Class | Proposed behavior |
|---|---|---|---|---|---|
| DS-C1 | **Filament mass ≈ density × (shell + infill × interior).** Slicer defaults: 2 walls, 15–20 % sparse infill, 4–5 top / 3–4 bottom layers; Cura's infill line spacing makes the infill fraction equal the density setting. | ORCA-PROC, PRUSA-INI, CURA-DEF. | evidence | **m** | M2: a simple estimate, roughly ±20 %. |
| DS-C2 | **Strength comes from walls; add walls before infill.** 10–15 % infill is usually enough. | PRUSA-INFILL, HACKSPACE (extra perimeters ~2.5× more filament-efficient than infill, one bending test), BP-W4. | evidence | **r** | When least cost meets a load: suggest wall count, not infill. |
| DS-C3 | **Print time is set by volumetric flow, the number of layers and a minimum layer time**: about 8–12 mm³/s on a standard hotend, 15–20 on Prusa's Nextruder, 21 for Bambu PLA profiles; minimum layer time 3–20 s by slicer and material. Acceleration is the main error in simple estimates. | PRUSA-MVS, ORCA-FIL, CURA-DEF, MEDINA19 (<8.5 % with a calibrated speed model; up to 59 % with programmed speeds). | evidence | **m** | M3: one rule, a rough estimate. |
| DS-C4 | **Supports cost filament and time, and leave rough faces.** Turn the part, chamfer the overhang, split. | BP-S1, BP-S2. PAGE26: support mass is the hardest thing to estimate (45 % weighted error). | evidence | **m** | M5: rough. |
| DS-C5 | **Removing volume saves only where infill dominates.** A shell-dominated part (thin walls, small) saves little by hollowing; a block saves a lot by pocketing. | Our mass model (DS-C1); PL-COST (volume vs cost, mostly powder/resin) **(1 src)**. | evidence | **m** | M2 reports the shell / infill split; suggestions follow it. |
| DS-C6 | **Layer height trades time for finish**: time scales roughly with 1 / layer height, less than proportionally (×1.85 from 0.2 to 0.1 mm in one test). | 3DPRINTERLY-LH, XYZDIMS *(both community)*. | evidence | **i** | Mentioned with DS-S1. |
| DS-C7 | **Small or tall thin parts are limited by minimum layer time; print several at once.** Unit cost falls with batch size and flattens after 6–7 parts. | ORCA-PROC / CURA-DEF (min layer time), HK24, BAUM17. | evidence | **m** | M3 reports the per-layer share of the time. |
| DS-C8 | **Orientation's effect on time is case-specific** (laying an L-bracket flat cut 58 % in one vendor case; standing a bracket up was faster in another). | CATI, FACFOX. *Disagree*: by design. | evidence | **i** | Compare variants with M3 instead of a rule. |
| DS-C9 | *Dropped:* a universal "cost per gram" or labour model. Labour was 42 % of cost in one batch study; it depends on the user. | HK24. | evidence | **d** | Cost = grams × the user's `filament_price` only. |

### 3.2 Rugged / outdoor

| # | Rule | Evidence | Kind | Class | Proposed behavior |
|---|---|---|---|---|---|
| DS-R1 | **Material for heat and sun:** PLA softens at 54–60 °C (HDT) and is not for outdoor use; PETG HDT ~68 °C, fine below ~80 °C in shade; **ASA is the outdoor material** (HDT ~93–103 °C, UV resistant); ABS yellows and embrittles in UV. A car dashboard reached ~69 °C after one hour in sun. | BAMBU-PLA, PM-PLA, PRUSA-MAT, PRUSAMENT-PETG, PM-ASA. UV ageing: MAT23 (ABS −6.5 to −6.9 % tensile after 98 days; ASA ±3 %; mild exposure), MT26 (QUV: ASA kept ductility). ASU18. | evidence | **i** | From the `material` setting: note PLA for rugged parts; suggest ASA (or PETG in shade). |
| DS-R2 | **Dark colors heat up more in sun.** | BSEN16795 (standard method) **(1 src for the effect on prints; no measured °C for printed parts)**. | evidence | **i** | Provisional note. |
| DS-R3 | **No water traps:** upward-facing pockets in the installed orientation get a drain (2–3 mm at the lowest point **(1 src: vendor)**); tops shed water; drip edges kick out. | PRUSA-WATER (prints are not watertight), ZBOTIC *(vendor)*, CC-DRIP (building-scale tests). | evidence | **m** | Metric: water traps (M11). Suggest a drain hole or a slope; the diameter is provisional. |
| DS-R4 | **Watertight walls need 3–4+ perimeters** (and more flow/temperature in the slicer). | PRUSA-WATER, ZBOTIC *(vendor; 4–5 for IP65+)*. | evidence | **r** | Report "set ≥ 4 walls" for sealed enclosures. |
| DS-R5 | **Seals: design O-ring grooves to the Parker tables**, e.g. 1.78 mm cord: 1.27–1.37 deep × 2.57–2.72 wide; 2.62 mm cord: 1.88–2.03 × 3.45–3.61; face-seal squeeze ≤ ~30 %, gland fill 60–85 %. The sealing surface must be smooth (32 µin RMS): print it on a vertical wall or a flat top (DS-S1), or finish it. | PARKER (handbook, standard reference). Synthesis with BUJ19 / DS-S1. | evidence | **r** | Rubric for sealed parts; a groove helper is a phase-3 idea. |
| DS-R6 | **IP codes** (reference): IPX5/6 water jets 12.5 / 100 L/min for 3 min, IPX7 1 m for 30 min; the water digit is not cumulative. | IP-GUIDE (summary of IEC 60529). | evidence | **i** | Used when the user names an IP target. |
| DS-R7 | **Impact and drops:** orient so loads and impacts run along layers (PLA 63 MPa flat vs 31 upright); add perimeters; round outside corners with **outside radius = inside radius + wall**. | CNCK-45, DESU20 (upright impact specimens weakest), HACKSPACE. Corners: PL-CORNER, RJC (injection molding), BP-R2 (Stratasys). *No FDM drop-test data found.* | evidence | **m** + **r** | M7 lists sharp outside corners; suggest radii by the formula. |
| DS-R8 | **Fasteners outdoors:** heat-set inserts or nuts rather than threads in plastic for parts that are reopened; 316 stainless near the coast. | BP-T5, MH-FAST *(vendor)*, BRUNDLE *(vendor)*. | evidence | **r** | Rubric. |
| DS-R9 | *Dropped:* a creep rule (PLA vs PETG under sustained load). | One short-term creep paper (SVJME22); no comparison found. | evidence | **d** | Revisit if a second source appears. |

### 3.3 Soft / handheld

| # | Rule | Evidence | Kind | Class | Proposed behavior |
|---|---|---|---|---|---|
| DS-H1 | **Power-grip handles about 30–40 mm across**; comfort peaked at ~19.7 % of hand length. Smaller grips give more finger force. *Disagree:* one source puts the optimum at 37–50 mm (41 ideal). | KONG05 + KONG03 (one group), LICHANG23 (review), EHS *(vendor)*. | evidence | **r** | Rubric: measure the grip with a section; suggest 30–40 mm. |
| DS-H2 | **Soft forms on FDM: avoid gently domed tops** (DS-S1), or tilt the part / use variable layer height; organic supports leave fewer scars. | CURVI19, LIV17, 3DJAKE-VLH, PRUSA-ORG **(1 src for the scar claim)**. | evidence | **m** + **r** | M6 on the up-facing curved area. |
| DS-H3 | **Curvature-continuous (G2) blends only matter on glossy or finished parts**; a circular fillet shows a highlight break. | AUTODESK-G2, MCNEEL-G2. | evidence | **i** | Note when the user will sand/paint; build123d has no G2 fillet, so no suggestion otherwise. |

---

## 4. The styles

A **style** is a short name the user picks for a part; there are five. It decides which metrics the review
highlights, which rubric questions it asks and which thresholds produce a **suggest**. All
styles also apply the general rules (§2) at **note** level. The definitions are ours (§1); the
rules they cite are sourced.

**Organic / soft:** included, narrowly, as **soft / handheld**. The curvature-preference
evidence (DS-G8) is too weak and fashion-dependent to justify a general "organic" style, but
parts held in the hand have their own sourced rules (grip size, domed-top stepping, supports)
that the other styles lack.

### 4.1 functional (default)

*It does its job, prints well and looks deliberate, not decorated.*

- **Looks for:** visible faces oriented well (DS-S1, DS-S2); supports on show faces (DS-C4);
  a place for the seam (DS-S3); edges treated consistently where they are treated (DS-G1);
  part and fastener economy (DS-G2, DS-G3); signifiers (DS-G5).
- **Metrics:** M5 supports, M6 stepping, M7 edges, M9 economy, M10 seam corners; M2/M3 shown.
- **Suggest when** *(proposed, ours)*: supports touch a face the user called visible; > 2
  screw sizes; a show face has > 20 % of its area in the stepping band (M6); no sharp contour
  corner on a part with a show side (M10 < 0.1).
- **Typical suggestions:** "Turn it 90° so the front is a vertical wall (no support scars)";
  "Use M3 for all four screws instead of M3 + M4"; "Add a 0.6 mm vertical groove on the back
  for the seam".

### 4.2 modern / minimal

*Few elements, one radius language, clean surfaces, nothing that doesn't need to be there.*

- **Looks for:** DS-G1 strictly (one edge-break size + at most one styling radius); DS-G2
  (fewest features, flush faces); no fasteners on show faces (*definition, ours*; DFA's
  fastener economy DS-G3 supports fewer of them); symmetry where function allows (DS-G7);
  curved edges (DS-G8); signifiers kept despite the minimal look (DS-G5, NNG-H8).
- **Metrics:** M7 (treated share, distinct radii), M8 symmetry, M9 face count, M6 stepping on
  show faces, M10.
- **Suggest when** *(proposed, ours)*: < 90 % of outside edge length treated (bed edges
  excluded); more than one edge-break size or more than one styling radius, or > 1 chamfer size; best mirror symmetry < 0.98 with no
  functional reason (ask); holes or screw heads on faces the user calls visible.
- **Typical suggestions:** "Radii 1, 1.5, 2 and 4 mm: use 1 mm edge breaks and 4 mm for the
  vertical corners"; "Move the screws to the underside or behind a press-fit cover"; "The lid's
  opening notch is the only cue for how to open it: keep it".

### 4.3 The industrial look: functional with `EDGES = "chamfer"`

Industrial/utilitarian is **not a separate style** (decision 1, §9): no design source defines it
beyond an encyclopedia article ("machine aesthetic") and a course blog. Its look is functional
plus two choices the script can state:

- `EDGES = "chamfer"`: chamfers are the edge language (DS-S4, they print at a constant angle);
  the review suggests when fillet length exceeds chamfer length or more than two chamfer sizes
  appear (DS-G1).
- Exposed standard fasteners of one size (DS-G3), ribs at wall thickness (BP-R4/R5), no fake
  features (DS-G6), knife edges broken (BP-R3): rubric items, as in functional.

`EDGES = "fillet"` does the same for a rounded language (any style).

### 4.4 least cost

*Least filament and print time that still does the job.*

- **Looks for:** supports (DS-C4); infill-dominated volume that could be pocketed (DS-C5);
  parts dominated by per-layer time (DS-C7); walls vs infill for strength (DS-C2);
  orientation compared by numbers, not a rule (DS-C8); layer height (DS-C6).
- **Metrics:** M2 mass (and cost if `filament_price` is set), M3 time with its breakdown, M5
  supports. For each suggestion the AI may build a variant and compare the two with M2/M3.
- **Suggest when** *(proposed, ours)*: support mass > 10 % of part mass; infill > 50 % of the
  extruded volume (pocketing pays); per-layer share > 50 % of the time (print several);
  a variant the AI tried saves > 10 % of mass or time (the estimates are rough: smaller
  differences are noise).
- **Typical suggestions:** "Lay it on its side: supports drop from 6.1 g to 0 and time from
  48 to 31 min (rough estimate)"; "Pocket the underside with 2 mm walls: −18 g (infill was 70 % of
  the mass)"; "It is a 400-layer pin: print four at once, the time per part falls ~3×".

### 4.5 rugged / outdoor

*Survives sun, water, heat, drops and repeated opening.*

- **Looks for:** material (DS-R1, DS-R2); water traps and drainage in the installed
  orientation (DS-R3); sealing walls and grooves (DS-R4, DS-R5); impact orientation, walls and
  outside radii (DS-R7); inserts and stainless hardware (DS-R8); target IP code (DS-R6).
- **Metrics:** M11 water traps (with `UP` pointing up), M7 sharp outside corners, M5; wall
  count for sealed parts is a slicer setting (DS-R4).
- **Suggest when** *(proposed, ours)*: the material setting is PLA, or unset (ask); any water
  trap over 0.5 cm³ (M11); any sharp outside edge (M7; the suggestion gives outside radius =
  inside radius + wall); screws threaded straight into plastic on a part opened more than a few
  times (rubric).
- **Typical suggestions:** "Print it in ASA: PLA softens at ~55 °C, a part in the sun gets
  hotter"; "The top pocket holds 2.3 cm³ of water: add a 3 mm drain at the low corner, or
  slope the floor 5°"; "Outer corners r = inner r 1 + wall 2 = 3 mm".

### 4.6 soft / handheld

*Comfortable in the hand, rounded, smooth where it is touched.*

- **Looks for:** grip size (DS-H1); rounded outside edges (DS-G8, M7); domed tops and shallow
  curves stepping (DS-H2, DS-S1); supports on held surfaces; G2 only if finished (DS-H3);
  signifiers for grip and buttons (DS-G5).
- **Metrics:** M7 (rounded share, radii), M6 stepping, M5 supports; grip diameter from a
  section (rubric, no automatic handle detection).
- **Suggest when** *(proposed, ours)*: sharp outside edges > 5 % of edge length on held
  surfaces; grip outside 30–40 mm; > 15 % of the up-facing area in the stepping band.
- **Typical suggestions:** "The handle is 26 mm across: 32–36 mm is more comfortable"; "The
  dome steps visibly at 0.2 mm layers: print it on its side or use variable layer height".

### 4.7 Where the style lives

1. **Part script:** `STYLE` in `Dims` (a variant can override it:
   `VARIANTS = {"outdoor": dict(STYLE="rugged")}`). The template has `STYLE: str = ""`, which
   means "use the workspace's". A module-level `STYLE` also works.
2. **Workspace:** `style = "modern"` in `b123d-print.toml` for a project whose parts share a look.
3. **Default:** `functional`.

Names: `functional`, `modern`, `least_cost`, `rugged`, `soft` (also accepted: `minimal`,
`least cost`, `outdoor`, `handheld`, and `industrial`, which means functional). Anything else
is an error that lists them. When a user starts a new part and has said nothing about looks,
the AI asks **once**; a blank answer means functional. One style per part, no modifiers; the
cost numbers are always shown (decision 2).

**Styles are files.** Each built-in style is a small TOML file (`src/b123d_print/data/styles/`)
holding its label, description, its thresholds (the "Suggest when" values above) and its
`review` text (the rubric). Users add their own in `~/.config/b123d-print/styles/` or the
workspace's `styles/`; the first found wins (workspace, user, built-in), so a file with a
built-in's name replaces it, and `based_on` starts from another style. The fields and an example
are on [Design review](using/design-review.md#custom-styles).

Optional script fields, also in `Dims` or at module level:

- `SHOW = ["+Y", "+Z"]`: the sides seen in use, in print orientation. Stair-stepping (M6) is
  then measured on those sides only, and supports under a visible side are flagged. Without
  `SHOW` the AI asks which sides show when it matters, or judges all faces (decision 5).
- `UP = "+Y"`: the side that points up in use, for water traps (M11). Default `+Z`.
- `EDGES = "chamfer"` or `"fillet"`: the edge language (§4.3).

---

## 5. `design_metrics`

An MCP tool and a CLI command that compute numbers for a built part:

```
design_metrics(name, variant=None, style="", up="", as_json=False)     # MCP
b123d-print metrics [parts...] [--variant K] [--style S] [--up +Y] [--json]   # CLI
```

It builds the part (in the sandbox, over MCP), computes M1–M11 for each printable part, then
the findings the style's thresholds trigger (§4), each citing its rule. It never fails and
changes nothing.

Settings it reads: the printer profile's nozzle and layer height (generic: 0.4 and 0.2), the
material profile's new `density` field (PLA 1.24 when no material is set, and it says so), and
three new optional settings: `style`, `filament_price` (per kg; a cost appears when set) and
`print_flow` (mm³/s for the time estimate, default 10). Printer profiles are unchanged:
they come from OrcaSlicer as before.

**The estimates are simple on purpose** (decision 7): filament is roughly ±20 %, time and
supports are rough estimates, and the output says so next to every number. They are for
comparing two versions of a part and for spotting what dominates (supports, infill, layer
count), not for quoting. No slicer calibration is claimed.

*Background only:* during the research a shell + infill model of this kind was compared with
Bambu Studio's own figures on ten simple shapes at default settings and landed within a few
per cent for filament; time depended much more on the printer's speed and acceleration. That
comparison is why the filament rule is trusted to roughly ±20 % across settings and why time is
only a rough figure; it is not a calibration, and no test depends on it.

### 5.1 M1: size and proportions

Bounding box X × Y × Z, volume, surface area, sorted aspect ratios. **Report only** (DS-G9).

### 5.2 M2: filament mass (and M4: cost)

```
T_wall = 2 walls × 1.1 × nozzle            (≈ 0.88 mm at 0.4)
T_top  = 5 × layer,  T_bot = 3 × layer      (the slicers' defaults, DS-C1)
per triangle of the part's mesh: t = max(T_top·n_z if n_z > 0 else T_bot·|n_z|,  T_wall·√(1 − n_z²))
shell    = min(V, Σ area × t)
extruded = shell + 15 % × (V − shell)
grams    = extruded × density;   cost = grams × filament_price / 1000
```

Output: grams, extruded volume, the shell and infill shares (DS-C5), cost. Stated as **a simple
estimate, roughly ±20 %**.

### 5.3 M3: print time

One rule, labeled **rough estimate**:

```
minutes = (extruded + support volume) / print_flow  +  layers × 3 s
```

`print_flow` (default 10 mm³/s, a standard hotend: PRUSA-MVS gives 8–12; high-flow hotends
20 and more) is the one setting that adjusts it. 3 s per layer stands for layer change, travel
and seam (ours; the slicers' minimum layer time, 3-20 s, is the floor for small layers, DS-C3);
the output reports the per-layer share, which is what makes small tall parts slow (DS-C7).

### 5.4 M5: supports

From the overhang analysis: downward faces steeper than `max_overhang` that are not bridges
within `max_bridge`, in print orientation.

```
column  = Σ area × |n_z| × height above whatever is below it (ray down; the bed if nothing)
support = 20 % × column  (supports are roughly a fifth solid)
```

Output: supported area, grams, and which faces. Rough.

### 5.5 M6: stair-stepping (surface quality)

From the mesh: cusp height `h_c = layer × |n_z|` (DS-S1), and the **stepping band**, the area
tilted 1–30° from flat (shallow slopes, not flat faces), up-facing and down-facing. Output:
band area (cm²) and its share of the up-facing area, limited to the `SHOW` sides when set.

### 5.6 M7: edge treatment

For **outside (convex) edges**, by length:

1. **Edge pairs:** for each edge between two faces, the angle between their normals at the
   midpoint; under 5° is tangent (a smooth seam); convex vs concave by a probe just inside the
   solid along −(n1 + n2).
2. **Fillet faces:** cylindrical or toroidal faces with a tangent edge, spanning under 180°
   (holes from `holes()` and full bosses excluded). Length = area / (radius × angle); convex
   when the outward normal points away from the centre of curvature, else an inside fillet.
3. **Chamfer faces:** planar faces at most 3 mm wide between two convex 20–70° turns; size =
   the leg (width × cos of the turn).
4. **Sharp:** other convex edges turning more than 20°.
5. **Bed edges** (on the lowest Z) are counted apart; BedEdge already checks them. Hole rims
   are not counted.

Output: sharp / filleted / chamfered shares, distinct radii (within 0.05 mm) as edge breaks
(≤ 1 mm) or styling radii (DS-S9), chamfer sizes, inside radii, bed edges, and fillets that face
down past the overhang limit (DS-S4). On imported meshes every edge is sharp: read M7 with that
in mind for remixes.

### 5.7 M8–M11

- **M8 symmetry:** vol(part ∩ mirror) / vol(part) for mirrors about the planes through the
  bounding-box centre; best of x and y (DS-G7).
- **M9 economy:** printable parts, solids, faces; round holes (`holes()`, minus hole
  compensation) matched to the clearance, heat-set insert or pilot size of M2–M8 screws (BP-T2,
  BP-T6), and the number of distinct screw sizes (DS-G3). A guess, and the output says so.
- **M10 seam corners:** the share of layers whose outer contour has a corner turning more than
  30° (DS-S3).
- **M11 water traps:** with `UP` pointing up, a voxel grid (1 mm; 0.5 mm under 30 mm) with a cell
  of air around the part; air drains when it can reach the sides or the bottom moving sideways or
  down. Air that cannot drain but is open to the top is a trap (volume, centre, low point);
  sealed voids are not (DS-R3).

### 5.8 Tests

`tests/test_metrics.py`, on shapes with known answers: a 60 × 40 × 20 box is all sharp,
symmetric, with seam corners on every layer; filleted vertical edges give exactly their 80 mm
of fillet and radius 3; all edges filleted is all rounded; a top chamfer gives size 1; a hole is
not a radius; a cylinder has no seam corner; a cup holds its inner volume of water and does not
with a drain hole or turned over; a T on a post has the analytic support column; the filament
estimate equals the shell formula for a cube and grows with infill; the time rule is the stated
formula; the findings fire at the thresholds; styles and directions parse. Sanity tests only:
no slicer fixtures.

---


## 6. `design_review`

An MCP **prompt** (`design_review(name, style="")`) that carries this page's rules, condensed
(`src/b123d_print/data/design_review.md`). It is the step after `verify_part`:

1. **Style:** `style` argument, else the script's `STYLE`, else the workspace, else ask once
   (default functional). Say which one is used.
2. **Print checks first:** `check` must have no FAIL. If it has, stop: report them and do not
   review the design (a design review of an unprintable part is noise).
3. **Numbers:** `design_metrics(name)`.
4. **Look:** `render_preview` from the angles the part is seen in use (ask which faces show,
   if it isn't obvious), and sections where a metric points (a handle, a pocket, a trap).
5. **Judge** the general rules (note level) and the style's rubric (suggest level, using the
   style's thresholds). Every finding cites a rule ID and its evidence: a metric value or what
   the render shows.
6. **Report** (short):
   - style, and the 4–6 metrics that matter for it (mass, time, supports, edge shares...);
   - 3–7 findings, most valuable first: rule ID, what and where, the concrete change with
     numbers, the expected effect (e.g. "−6 g, −17 min, no support scars on the front"), and
     the trade-off;
   - what is fine (one line);
   - "Shall I apply any of these?" **It does not change the part without the user's OK.**
7. **If the user says yes:** change Dims (a variant if both should stay), then the normal
   verify loop (build, render, sections, `check`), then `design_metrics` again to show the
   before/after numbers.

The AI may build a **trial variant** to quantify a least-cost suggestion (e.g. a turned
orientation), but it reports the numbers and leaves the script as it was unless the user
agrees; trial variants are not written into the part.

## 7. AGENTS.md step

AGENTS.md (both copies) has a **Design review (after the print checks pass)** section: every
part has a style; ask once for a new part; run the review when `check` has no failures; report 3–7
suggestions with rule IDs; **do not change the part without the user's OK**; the estimates are
rough; never a proportion rule. `design_part_from_photos` asks for the style with the
dimensions, and `verify_part` and the report step offer the review. The rubric the prompt
carries is `src/b123d_print/data/design_review.md`.

## 8. Implementation

- `src/b123d_print/metrics.py`: M1–M11, the style findings and the text report (cites `DS-*`).
- `src/b123d_print/styles.py` and `data/styles/*.toml`: the style files, their lookup
  (workspace, user, built-in), `based_on`, and errors for unknown fields; `b123d-print styles`.
- Settings: `style`, `filament_price`, `print_flow`; `density` in material profiles. Printer
  profiles unchanged.
- MCP: the `design_metrics` tool and the `design_review` prompt; CLI: `b123d-print metrics`.
- `STYLE` in the part template; optional `SHOW`, `UP`, `EDGES`.
- Tests: `tests/test_metrics.py` (known shapes), `tests/test_design_rules.py` (the `DS-*` IDs in
  code, AGENTS.md and the rubric exist on this page; class-m rules have a metric; class-d rules
  are never cited).

## 9. Decisions (review of 2026-10-18)

1. **Industrial** is folded into functional as `EDGES = "chamfer"` with exposed standard
   fasteners. Five styles.
2. **One style per part**, no modifiers; the cost numbers are always shown.
3. **STYLE lives in `Dims`** (variants can override it), then the workspace, then functional.
4. **No speed classes**, and printer profiles stay as they come from OrcaSlicer; one optional
   setting, `print_flow`, adjusts the time estimate.
5. **SHOW** is optional; without it the AI asks or judges all faces.
6. The **thresholds** marked *proposed (ours)* are the starting values.
7. **Simple estimates**: filament roughly ±20 %, time one rule labeled "rough estimate"; no
   slicer-calibration tests or claims.
8. **Custom styles**: the built-in styles ship as the same kind of file a user writes; user and
   workspace style folders; `based_on`; a file with a built-in's name replaces it; clear errors
   for unknown fields.

---

## Sources

All fetched 2026-10-18. *(peer-reviewed)*, *(primary)*, *(vendor)*, *(community)* as in
BEST_PRACTICES.

**Design principles and aesthetics**

- RAMS *(primary)*: Vitsœ, "Dieter Rams: ten principles for good design", https://www.vitsoe.com/us/about/good-design
- HEK06 *(peer-reviewed)*: Hekkert, "Design aesthetics: principles of pleasure in design", Psychology Science 48(2) 2006, https://pure.tudelft.nl/ws/portalfiles/portal/54686438/Hekkert_P._Design_aesthetics_principles_of_pleasure_in_design.pdf
- PBH16 *(peer-reviewed, abstract)*: Post, Blijlevens & Hekkert, Acta Psychologica 163 (2016), https://research.tudelft.nl/en/publications/to-preserve-unity-while-almost-allowing-for-chaos-testing-the-aes/
- KAR07 *(peer-reviewed)*: Karjalainen, "It Looks Like a Toyota", IJDesign 1(1) 2007, https://ijdesign.org/index.php/IJDesign/article/view/43/14
- C77 *(community)*: Core77 Boards, "Small fillets", https://boards.core77.com/t/small-fillets/31865
- BN06 *(peer-reviewed)*: Bar & Neta, "Humans prefer curved visual objects", Psychological Science 17(8) 2006, https://moshebar.org/_files/ugd/a77db7_5598c791a95a4436960eb2fe671ca1e5.pdf
- BPG16 *(peer-reviewed)*: Bertamini et al., "Do observers like curvature or do they dislike angularity?", Br J Psychol 2016, https://pmc.ncbi.nlm.nih.gov/articles/PMC4975689/
- SB09 *(peer-reviewed, abstract)*: Silvia & Barona, Empirical Studies of the Arts, https://synapsesocial.com/papers/W1972399654
- COT17 *(peer-reviewed)*: Cotter et al., "Curve Appeal", i-Perception 2017, https://pmc.ncbi.nlm.nih.gov/articles/PMC5405906
- GMN16 *(peer-reviewed review)*: Gómez-Puerto, Munar & Nadal, Front. Hum. Neurosci. 9:712, https://pmc.ncbi.nlm.nih.gov/articles/PMC4709714/
- CAR10 *(peer-reviewed)*: Carbon, "The cycle of preference", Acta Psychologica 134 (2010), https://www.experimental-psychology.de/ccc/docs/pubs/Carbon2010b.pdf
- JH-ERP *(research paper)*: Jacobsen & Höfel, symmetry and beauty judgments (ERP), https://psychologie.lw.uni-leipzig.de/fechner/generalinfo/PDFs/TJacobsen.pdf
- VRL17 *(peer-reviewed)*: Valencia-Romero & Lugo, Design Science 3:e11 (2017), https://www.cambridge.org/core/product/E7E6A31AFA23C6FB5BC16DE074EC981A/core-reader
- CVS10 *(peer-reviewed)*: Creusen, Veryzer & Schoormans, European Journal of Marketing (2010), https://emerald.com/insight/content/doi/10.1108/03090561011062916/full/html
- MCM10 *(peer-reviewed, abstract)*: McManus, Cook & Hunt (2010), https://synapsesocial.com/papers/W1993204175
- SWT16 *(peer-reviewed)*: Spehar, Walker & Taylor, Front. Hum. Neurosci. (2016), https://pmc.ncbi.nlm.nih.gov/articles/PMC4937063
- DEV *(press)*: ScienceAlert on Keith Devlin, https://www.sciencealert.com/mathematicians-argue-that-the-golden-ratio-is-not-the-formula-for-beauty
- SUL *(primary)*: Sullivan, "The Tall Office Building Artistically Considered" (1896), https://ocw.iti.hr/courses/architecture/4-205-analysis-of-contemporary-architecture-fall-2009/readings/MIT4_205F09_Sullivan.pdf
- NOR08 *(primary)*: Norman, "Signifiers, not affordances", https://jnd.org/signifiers-not-affordances/
- NNG-AFF: Nielsen, "Top-10 Application-Design Mistakes" (2008), https://www.nngroup.com/articles/top-10-application-design-mistakes-2008/
- NNG-H8: Fessenden, "Aesthetic and Minimalist Design" (2021), https://www.nngroup.com/articles/aesthetic-minimalist-design/
- Machine aesthetic (encyclopedia, used only to say the industrial style has no design source): https://en.wikipedia.org/wiki/Machine_aesthetic

**Design for assembly**

- DFA-PALNI *(open textbook)*: Gagnon & Bearman, *Design for Manufacture and Assembly*, ch. 5, https://pressbooks.palni.org/designmanufactureassembly/chapter/chapter-5/
- DFA-MTU *(university lecture)*: Sutherland, MEEM 4685/5685 lecture 19, https://engineering.purdue.edu/LSM/courses/MEEM4685_5685/ERDM_Lecture19.pdf
- DFA-ACC: Schenkelberg, Accendo Reliability, https://accendoreliability.com/design-for-assembly/
- DFA-FIC *(vendor)*: Fictiv, https://www.fictiv.com/articles/keep-the-assembly-line-happy-10-design-for-assembly-rules-to-live-by
- DFA-WEV *(trade)*: Wevolver, https://www.wevolver.com/article/design-for-assembly-dfa
- DFMA-CO *(vendor)*: Boothroyd Dewhurst, https://dfma.com/resources/assembly-cost-estimating.asp

**FDM surfaces, seams, DfAM**

- LIV17 *(peer-reviewed)*: Livesu et al., "From 3D models to 3D prints", Eurographics STAR 2017, https://arxiv.org/pdf/1705.03811
- WAS17 *(peer-reviewed)*: Wasserfall, Hendrich & Zhang, "Adaptive slicing for the FDM process revisited", IEEE CASE 2017, https://tams-www.informatik.uni-hamburg.de/publications/2017/Adaptive%20Slicing%20for%20the%20FDM%20Process%20Revisited.pdf
- BUJ19 *(peer-reviewed)*: Buj-Corral et al., Materials 12(23):3834 (2019), https://pmc.ncbi.nlm.nih.gov/articles/PMC6926983/
- CURVI19 *(peer-reviewed)*: Etienne et al., "CurviSlicer", ACM ToG 38(4) 2019, https://par.nsf.gov/servlets/purl/10132343
- BOOTH17 *(peer-reviewed)*: Booth et al., "The Design for Additive Manufacturing Worksheet", J. Mech. Des. 139(10), https://engineering.purdue.edu/cdesign/wp/wp-content/uploads/2017/08/Joran-JDM.pdf
- THOMPSON16 *(peer-reviewed, abstract only)*: Thompson et al., CIRP Annals 2016, https://research.utwente.nl/en/publications/design-for-additive-manufacturing-trends-opportunities-considerat/
- MD-XOM: Paulsen (Xometry), Machine Design 2017, https://www.machinedesign.com/3d-printing/best-practices-fdm-3d-printing
- XOM-MINI: https://www.xometry.com/resources/3d-printing/mini-guide-fdm-3d-printing/
- PL-ORIENT: Protolabs, https://www.protolabs.com/en-gb/resources/blog/considerations-for-3d-printed-part-orientation/
- STR-SURF: Stratasys, "Designing for optimal FDM surface finish" (2019), https://www.stratasys.co.jp/siteassets/industries-and-applications/3d-printing-applications/production-parts/ab_fdm_surfacefinish_0819a.pdf
- HUBS-FDM: https://www.hubs.com/knowledge-base/how-design-parts-fdm-3d-printing/
- HUBS-ORIENT: https://www.hubs.com/blog/print-orientation/
- HUBS-POST: https://www.hubs.com/knowledge-base/post-processing-fdm-printed-parts/
- PRUSA-MODEL: https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135
- PRUSA-SEAM: https://help.prusa3d.com/article/seam-position_151069
- PRUSA-IRON: https://help.prusa3d.com/article/ironing_177488
- PRUSA-FUZZY: https://help.prusa3d.com/en/article/fuzzy-skin_246186/
- PRUSA-CUT: https://help.prusa3d.com/article/cut-tool_1779
- PRUSA-BLOG: https://blog.prusa3d.com/a-journey-through-craftsmanship-and-design-led-by-open-source-3d-printers_104681/
- ORCA-SEAM: https://github.com/SoftFever/OrcaSlicer/wiki/quality_settings_seam
- OBICO-SEAM *(vendor)*: https://obico.io/blog/orcaslicer-seam-settings
- BIGREP-SEAM *(vendor)*: https://bigrep.com/posts/hiding-the-seams-3dprinting-bigrep-design/
- BIGREP-FC *(vendor)*: https://bigrep.com/posts/fillets-vs-chamfers-in-3d-printed-parts/
- STARFISH *(vendor)*: https://starfishmedical.com/?p=11797
- C77-LINE: Core77, "Making a 3D printed product line that doesn't look 3D printed", http://www.core77.com/posts/26486/In-the-Details-Making-a-3D-Printed-Product-Line-That-Doesnt-Look-Like-It-Was-3D-Printed
- HACKADAY-LINES: Hackaday on Slant 3D (2024), https://hackaday.com/2024/03/04/design-tips-to-hide-layer-lines-in-3d-printed-parts/
- SOVOL-SPLIT *(vendor)*: https://www.sovol3d.com/blogs/news/how-to-split-large-3d-models
- 3DPRINTERLY-PILLOW *(community)*: https://3dprinterly.com/how-to-fix-rough-top-layer-issues-pillowing-in-5-easy-ways/

**Cost and time**

- ORCA-PROC: https://github.com/SoftFever/OrcaSlicer/blob/main/resources/profiles/BBL/process/fdm_process_common.json and …/fdm_process_single_0.20.json
- ORCA-FIL: OrcaSlicer BBL filament profiles (Bambu PLA Basic @base), https://github.com/SoftFever/OrcaSlicer/tree/main/resources/profiles/BBL/filament
- PRUSA-INI: https://github.com/prusa3d/PrusaSlicer-settings-prusa-fff/blob/main/PrusaResearch/2.5.12.ini
- CURA-DEF: https://github.com/Ultimaker/Cura/blob/main/resources/definitions/fdmprinter.def.json
- PRUSA-INFILL: https://help.prusa3d.com/article/infill_42
- PRUSA-MVS: https://help.prusa3d.com/en/article/max-volumetric-speed_127176
- HACKSPACE *(magazine)*: Everard, "Experiments with strong 3D prints", https://magazine.raspberrypi.com/articles/experiments-with-strong-3d-prints
- MEDINA19 *(peer-reviewed)*: Medina-Sanchez et al., Materials 12(23):3982 (2019), https://pmc.ncbi.nlm.nih.gov/articles/PMC6926927
- PAGE26 *(peer-reviewed)*: Giovenali et al., PAGE-Net, Int J Adv Manuf Technol 144 (2026), https://iris.polito.it/retrieve/handle/11583/3011349/5cb3ece1-424b-40eb-acfd-7ec1fb261755/s00170-026-17892-2.pdf
- KORMANN26 *(peer-reviewed)*: Kormann et al., Proc. Design Society 6 (2026), https://www.cambridge.org/core/product/BBF88A25A0CCCB833A3F30F5CB7FDFB6
- HK24 *(peer-reviewed)*: Hernandez Korner et al., 3D Printing and Additive Manufacturing 11(1) (2024), https://pmc.ncbi.nlm.nih.gov/articles/PMC10880658
- BAUM17 *(peer-reviewed)*: Baumers et al., arXiv:1706.02090, https://arxiv.org/abs/1706.02090
- PL-COST: Protolabs, "3D printing cost", https://www.protolabs.com/resources/design-tips/3d-printing-cost/
- CATI: https://www.cati.com/?p=121419
- FACFOX *(vendor)*: https://facfox.com/docs/kb/how-to-reduce-the-cost-of-3d-printing-2
- 3DPRINTERLY-LH *(community)*: https://3dprinterly.com/which-layer-height-is-best-for-3d-printing/
- XYZDIMS *(community)*: https://xyzdims.com/?p=873
- Slicer estimates vs reality: Prusa forum https://forum.prusa3d.com/forum/prusaslicer/print-times-longer-than-cura/ ; PrusaSlicer issue https://github.com/prusa3d/PrusaSlicer/issues/12664 ; klipper_estimator https://github.com/annex-engineering/klipper_estimator
- Densities (datasheets): Bambu PLA Basic TDS https://www.additive-x.com/shop/mpattachments/file/viewonline/id/494/product_id/2236 ; Bambu ABS https://www.additive-x.com/shop/mpattachments/file/viewonline/id/566/product_id/2315 ; Bambu PETG https://www.additive-x.com/shop/mpattachments/file/viewonline/id/580/product_id/2330 ; Bambu TPU 95A HF https://www.additive-x.com/shop/mpattachments/file/viewonline/id/823/product_id/2584 ; Prusament PLA https://www.matterhackers.com/r/xFvGl8 ; Prusament PETG https://www.3dprintergear.com.au/assets/files/technical-data-sheet%20(1).pdf ; Polymaker ASA https://wiki.polymaker.com/polymaker-products/more-about-our-products/documents/technical-data-sheets/abs-asa/polylite-tm-asa

**Rugged, outdoor, handheld**

- BAMBU-PLA: Bambu PLA Basic TDS (above). PM-PLA: https://wiki.polymaker.com/polymaker-products/more-about-our-products/documents/technical-data-sheets/pla/polylite-tm-pla ; PM-ASA (above); PRUSAMENT-PETG (above)
- PRUSA-MAT: https://help.prusa3d.com/article/pla_2062 , https://help.prusa3d.com/article/petg_2059 , https://help.prusa3d.com/article/asa_1809 , https://help.prusa3d.com/article/abs_2058
- MAT23 *(peer-reviewed)*: Materials 2023, degradation of 3D-printed plastics, https://pmc.ncbi.nlm.nih.gov/articles/PMC10146359/
- MT26 *(peer-reviewed, abstract)*: Manufacturing Technology 26(1) 2026, https://mt.ujep.cz/artkey/mft-202601-0007_effect-of-accelerated-aging-on-the-mechanical-properties-of-fff-manufactured-polymers.php
- ASU18: https://news.asu.edu/20180516-discoveries-asu-study-hot-cars-can-hit-deadly-temperatures-within-one-hour
- BSEN16795 *(standard)*: https://knowledge.bsigroup.com/products/plastics-method-for-estimating-heat-build-up-of-flat-surfaces-by-simulated-solar-radiation
- PRUSA-WATER: https://help.prusa3d.com/article/watertight-prints_112324
- ZBOTIC *(vendor)*: https://zbotic.in/3d-printing-electronics-housings-water-and-dustproof-cases/
- CC-DRIP: https://www.constructioncanada.net/the-effectiveness-of-different-drip-edge-designs/
- PARKER *(handbook)*: Parker O-Ring Handbook ORD 5700, https://nfc.arizona.edu/sites/default/files/2022-02/parker_o-ring_handbook.pdf
- IP-GUIDE *(vendor summary of IEC 60529)*: https://indexenclosures.com/resources/ip-ratings-guide/
- CNCK-45: https://cnckitchen.com/blog/stop-printing-flat-the-45-secret-for-stronger-parts
- DESU20 *(peer-reviewed)*: Desu et al., Int J Adv Manuf Technol 107 (2020), https://www.torontomu.ca/content/dam/frames/publications/Desu_Rossi_Mankoo_Fayazbakhsh_Fawaz_2020.pdf
- PL-CORNER: https://www.protolabs.com/resources/design-tips/cutting-corners-on-injection-molded-parts/
- RJC *(vendor)*: https://rjcmold.com/guides/fillet-design-guide/
- MH-FAST *(vendor)*: https://www.matterhackers.com/articles/fasteners-for-3d-printing
- BRUNDLE *(vendor)*: https://www.fhbrundle.co.uk/lp/blog/faq-items/what-is-the-difference-between-grade-304-and-316-stainless-steel/
- SVJME22 *(peer-reviewed)*: short-term creep of AM polymers, https://www.sv-jme.eu/article/short-term-creep-behavior-of-different-polymers-used-in-additive-manufacturing-under-different-thermal-and-loading-conditions/
- KONG05 *(peer-reviewed)*: Kong & Lowe, Int J Ind Ergon 35(6) 2005, https://stacks.cdc.gov/view/cdc/197408 ; KONG03: https://stacks.cdc.gov/view/cdc/196025
- LICHANG23: Li & Chang, AHFE 2023, https://openaccess-api.cms-conferences.org/articles/download/978-1-958651-53-7_90
- EHS *(vendor)*: https://www.ehs.com/blogs/ergonomic-handle-design-considerations/
- 3DJAKE-VLH *(vendor)*: https://www.3djake.ch/en-CH/info/guide/variable-layer-height-in-3d-prints-how-to-avoid-unsightly-layer
- PRUSA-ORG: https://help.prusa3d.com/article/organic-supports_480131
- AUTODESK-G2: https://help.autodesk.com/cloudhelp/2014/ENU/Alias/files/GUID-9DD73E22-A5EF-4952-BB84-2CEE2109993C.htm
- MCNEEL-G2 *(community)*: https://discourse.mcneel.com/t/blendedge-or-filletedge/159197

**Unreachable or gated** (not used): Thompson et al. 2016 full text (403); Diegel, Nordin &
Motte book (login); Kumke et al. 2016 (not found); Markowsky 1992 and Green 1995 (bot check /
403); Westerman et al. 2012 (403); Komineas 2018 and Hopkinson & Dickens (blocked); Bambu wiki
seam page (402); All3DP (403); NN/g affordance article (404); MoMA Machine Art (403); NASA-STD-3000
handle data (not found); MDPI impact studies (403).
