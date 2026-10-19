# FDM design rules (sourced)

These are the design-for-FDM rules behind b123d-print's checks and its
[workflow rules](scripts/rules.md). They were collected from makers' design guides, slicer
documentation and published tests, and kept only where independent sources agree. For each
rule the tables say whether b123d-print **checks** it, **tells the agent** about it, or
**measures** it with a calibration print.

**Status:** the checks and coupons of plans P1 and P2 are implemented
([§17](#17-implementation-plan-and-status)); P3 is not yet. The code and AGENTS.md cite the
rule IDs (`BP-H3` in code, `[H3]` in AGENTS.md), and `tests/test_rules.py` keeps them in step
with this page.

Every source was fetched on 2026-10-17. Claims come from the fetched page, PDF or source file,
never from memory. Pages that could not be reached are listed under [Sources](#sources).

## How to read this

**Validation rule.** A rule is kept when at least **two independent publishers** agree on it.
These pairs count as **one** publisher:

- Formlabs' FDM guide and Hubs. Formlabs says its FDM values are based on Protolabs/Hubs
  estimates.
- The Xometry pages, the Xometry article on Wevolver and the Xometry webinar.
- Core77's snap-fit article, which reposts Fictiv.
- The Stratasys Direct 2017 and 2025 guides.

Vendor blogs (Sovol, QIDI) and community posts (forums, Fab Academy) are marked as such. They
count toward agreement but never stand alone. Single-source rules are marked **(1 src)** and are
not adopted as constants.

**Class**

- **a: check.** Automatable on the solid. The proposal says how it is measured and whether it
  fails or warns.
- **b: guidance.** Goes into `AGENTS.md` and the MCP prompts. Some of it is better delivered as a
  **helper** function, so the agent calls the rule instead of re-deriving it.
- **c: calibration.** The number depends on the printer and material, so a coupon print measures
  it and the result goes into the user's calibration or profile.
- **d: drop.** Slicer tuning rather than modeling, a single source, or contradicted.

**Profile.** **P** marks numbers that depend on the printer, nozzle or material. They belong in
the printer/material profile or a calibration value, never in a constant.

**Angles** are measured from vertical: 0° is a wall, 90° a flat ceiling. This matches the
existing overhang check, Hubs and Cura. PrusaSlicer's support threshold is measured from
horizontal.

**Clearances** are **per side** (radial) unless marked "total" (diametral). Most sources do not
say which they mean; where a source is ambiguous, the table says so.

Source keys (e.g. `PRUSA-MODEL`) are listed with their URLs under [Sources](#sources).

---

## 1. Walls and minimum feature size

| # | Rule | Value / range | Evidence (source: claim) | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| W1 | A feature thinner than one line width does not print as modeled. | < 1 line width (≈ 0.45 mm on a 0.4 mm nozzle) | PRUSA-MODEL: walls thinner than one perimeter are not printable. CURA-DEF: min feature size = line width / 4; thinner is dropped and thicker is widened to the min wall line (0.85 × nozzle). ORCA-CFG: `min_feature_size` 25% of nozzle; thinner features are not printed. PRUSA-ARACHNE: the same min-feature behavior. | P | **a** | **ThinFeature** (new, automatic): **fail** below 1 line width. |
| W2 | Minimum wall for a part that has to hold up: ≥ 0.8 mm floor, 1.2–1.5 mm recommended. | 0.8 floor, 1.2–1.5 rec. Outliers: JLC 1.6–2.5 by part size; SSD 4 × layer | PL-FDM 0.8. HUBS-KEY: >0.8 on all printers. XOM-PRO 0.75–1.0 capability, 1.5 recommended. HLH ≥1.0 supported / ≥1.2 unsupported. UZH 1.0. MAT 0.8–1.2. POLLEN ≥2 × nozzle. JLC size-scaled. SSD 4 × layer. | P | **a** | ThinFeature: **warn** below `min_wall`. Today min_wall = 2 lines (profile) or 0.8 (generic), which matches the floor. Keep "≥1.2 mm where strength matters" in AGENTS.md. |
| W3 | Model walls as whole multiples of the line width (≈0.45 / 0.9 / 1.35 / 1.8 mm at 0.4). With classic perimeters, 1–2 lines is a dead zone. | n × line width | PRUSA-MODEL: the multiples listed; 1–2 perimeters not printable. PRUSA-LP: use PrusaSlicer's "recommended thin wall thickness". HUBS-SHELL: shells as multiples of the nozzle. FR: ≤2 beads print poorly. | P | **b** | Already in AGENTS.md (with a printer set). ThinFeature reports the thinnest wall in lines, as info. Arachne slicers soften the dead zone, so no warning. |
| W4 | Strength comes from walls/perimeters, not infill. Add walls before infill. | — | PRUSA-INFILL: strength is set "mostly" by perimeters; 10–15% infill usual. CNCK-BEG, CNCK-NOZ, CNCK-EW: tests where wall thickness drives strength (2 → 4 perimeters: 20 → 33 kg). HUBS-SHELL: more shell rather than more infill. | — | **b** | AGENTS.md: a loaded feature's strength ≈ its wall thickness. Size walls and ribs for strength instead of relying on infill. Say in the report which features need extra perimeters. |
| W5 | Minimum vertical pin diameter. Pins under ~5 mm are perimeter-only and weakly attached: fillet the base, or use a metal pin. | min 1–3 mm (1 "possible", 2–3 "reliable"). Perimeter-only below 5 mm | HUBS-FDM: <5 mm perimeter only, fillet the base, metal pin if critical. UZH 3. FORMLABS-FDM 3 (from Hubs). HLH 1 reliable. XOM-PRO 1.2 capability / 1.5 recommended. JLC 2 mm at H ≤ 2D. SSD ≈2 mm (0.08 in). | P | **a** | **Pins** (new, automatic): convex cylinders with vertical axis. **Warn** at d < 2 mm. Info at d < 5 mm suggests a base fillet. |
| W6 | Free-standing pin/post height ≤ 5 × diameter. | H/D ≤ 5 | MF: avoid posts with H > 5D (they shear on layer lines). XOM-WEB: about 5×, 1.5 mm minimum. JLC: offers pins only up to H ≈ 2D. FR: high aspect ratios warp. | — | **a** | Pins: **warn** at H/D > 5. |
| W7 | Minimum gap between features (slot, gap between walls). | 0.5 (bureaus); 0.2–0.3 (desktop) | XOM-PRO 0.5 capability / 1 recommended. HLH 0.5. UZH 0.5. MAT 0.4. PRUSA-MODEL accuracy 0.2. OAK 0.15–0.3 radial. | P | **c** | Measured by the fit coupon (K2). An automatic "narrow slot" check is possible later. |

## 2. Holes

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| H1 | Vertical holes print undersize. Calibrate per printer and material, and compensate. | 0.1–0.25 mm on diameter (tuned desktop). >1 mm reported in one paper | CNCK-INS1: 0.1 (4.0 needed 4.1 in CAD). CNCK-INS2: ≈0.25. POLLEN, OAK: design ≈0.2 larger. SLIC3R, OPENSCAD, NOPHEAD: polygon and corner-cutting causes. PANICO2026: >1 mm on 6.35 mm holes. BAMBU-XY: calibrate per filament. | P | **c** | Already done: `HOLE_COMP` + `hole_coupon`. Keep. |
| H2 | Slicer hole compensation is per side (the diameter grows 2×), defaults to 0, and only affects closed holes in the XY plane. It does nothing for horizontal or partial holes. | — | BAMBU-XY: diameter grows by "twice the compensation value". BAMBU-AUTO: full circles only, ≤ 50 mm, horizontal plane. ORCA-CFG / ORCA-WIKI: default 0, positive enlarges. CURA-DEF: `hole_xy_offset` default 0. SLIC3R: per-side value. | — | **b** | AGENTS.md: compensate in CAD (HOLE_COMP), not in the slicer as well. Do not apply both. HOLE_COMP is on the diameter. |
| H3 | Horizontal holes (axis in XY): the top sags and prints small. Use a teardrop or flat (bridged) roof, support, or turn the part so the axis is vertical. Vertical-axis holes are the most accurate. | Teardrop roof at the overhang limit (45°) | CNCK-TIPS: the top of horizontal holes prints smaller. POLLEN: teardrop for functional holes. HUBS-FDM: rotate 90° to avoid support. XOM-MINI, XOM-WEV: orient holes vertically. B3DKIT: teardrop ratio 1.05–1.15. | P | **a** + helper | **Holes** (new, automatic): find concave cylindrical faces with a horizontal axis. **Warn** when d ≥ 2 mm and the roof is a plain arc: "top will sag; use `teardrop_hole()` or a flat bridged roof, or turn the part". The overhang check groups these faces as "horizontal hole" instead of loose faces. Helper `teardrop_hole(d, axis, angle=max_overhang)`. |
| H4 | Horizontal and vertical holes need different sizes for the same fit. | e.g. M3 self-tap: PLA 2.90 horizontal / 2.72 vertical | BAMBU-FORUM-SCREW: table per material and orientation. CNCK-TIPS: test each orientation. | P | **c** | Extend `hole_coupon` with horizontal holes, so the user can record a second value, `hole_comp_h` (K1). |
| H5 | Minimum hole diameter. | 1–2 mm | XOM-MINI, XOM-PRO 1. STAN 1. PL-FDM 2. UZH 2 (depends on depth). JLC ≥1.5, depth ≤ 3D. BAMBU-XY: below 1 mm hard to tune. OAK ≈ one line width. | P | **a** | Holes: **warn** at d < 1 mm. |
| H6 | For critical diameters, print undersize and drill or ream. | — | HUBS-FDM, SSD, XOM-MINI, FACFOX, CNCK-INS2. PANICO2026: drilling only works in a narrow feed/speed window, or it melts. | — | **b** | AGENTS.md: offer "ream to size" for precision bores (bearings, shafts). Model those holes undersize and state it in the report. |

## 3. Overhangs and bridges

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| O1 | Unsupported overhangs: design to 45°. 45–60° usually prints. Up to ~75° with strong (360°) cooling. Below 45° with a 0.25 mm nozzle. | 45° design; 45–75° by printer | HUBS-FDM 45°. XOM-PRO 45°. WEVOLVER-OH 45°. PRUSA-MODEL 45–60°, 75° on Nextruder/360° cooling, <45° at 0.25 nozzle. ORCA-WIKI 45–60°. CURA-DEF support default 50°. FAB22 test: 60° limit. | P | **a** + **c** | Exists (Overhang, `max_overhang` in the profile). Add the overhang ladder to the bridge coupon (K3), so `max_overhang` becomes a measured number per printer. |
| O2 | Downward edges and edges on the bed: chamfer, not fillet. A fillet's lowest part is a near-flat overhang. | 45° chamfer | PRUSA-MODEL, UM, BIGREP, MF: chamfer on the bed, fillets on vertical edges. BAMBU-FORUM-WARP: fillet only above 45°. *Disagree:* HUBS-FDM allows "chamfer or radius"; FACFOX says fillet. | — | **a** | Exists in AGENTS.md. New **BedEdge** check (automatic): curved faces meeting the bed whose lowest band is steeper than `max_overhang` → **warn** "fillet on a bed edge; use a chamfer". The overhang check today only catches this when `ignore_below` is 0. |
| O3 | Bridge length: no universal maximum. Design guides cap it for surface quality; tuned printers do far more. | 5–10 mm design limit. ~20–37 mm in tests. 50–80 mm with sag | HUBS-FDM <5 mm. XOM-PRO 10 mm. 3DMAG: UltiMaker 10 mm guideline; one PLA study 33–37 mm. FAB22: 22 mm clean. QIDI-BRIDGE (vendor): <20 clean, 50–80 sag. | P | **a** + **c** | **Bridge span** in the Overhang check: for each flat downward face, span ≈ 2 × the largest inscribed circle radius. **Warn** above `max_bridge` (new printer field, default 10 mm, measured by K3). |
| O4 | A flat ceiling must be held on two opposite sides. A ceiling off one wall is a cantilever and needs support. | — | HUBS-FDM, PRUSA-MODEL: bridges print between supports; a hanging ceiling needs support. Existing AGENTS.md rule. | — | **a** | Overhang: classify each flat downward face by its supported boundary. An edge is anchored when there is material just beyond it and just below the ceiling (a wall the bridge rests on). Points held by anchors on two opposite sides → bridge; else **cantilever**. Cantilevers are not exempt under `bridges_ok` and fail when `fail=True`. |
| O5 | Holes or pockets in a ceiling (counterbore over air, nut trap roof): print a one-layer sacrificial bridge, then drill it out. | ≥1 layer | HACKADAY-SB (tag page; no numbers). Search-level mentions of Orca's counterbore bridging, not verified. **(1 src)** | — | **b** (provisional) | Mention it as a technique in AGENTS.md next to nut traps. Leave it out of checks until a second source or a coupon confirms it. |
| O6 | Bridge flow, speed and fan; overhang cooling, temperature and layer height. | — | CURA-DEF, ORCA-WIKI, QIDI-BRIDGE, WEVOLVER-OH | P | **d** | Slicer tuning. |

## 4. Supports and orientation for strength

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| S1 | Design to avoid supports: reorient, split, chamfer, or model your own breakaway support. Supported surfaces come out rough. | — | PRUSA-MODEL, PRUSA-SUP, HUBS-FDM, ORCA-WIKI ("make overhang printable"), CNCK-45 (supports released by warping) | — | **b** | Exists ("say what needs supports"). Add the order to try: turn the part → chamfer → split → teardrop/roof shapes → supports. |
| S2 | Gaps that support has to be cleared out of should be ≥ 5 mm wide. | ≥5 mm | FR, XOM-WEB (0.2 in) | — | **b** | AGENTS.md. |
| S3 | Support Z/XY gaps and interface layers. | Z ≈ 50–75% of a layer; Cura XY 0.7 | PRUSA-SUP, CURA-DEF, ORCA-WIKI | P | **d** | Slicer tuning. |
| S4 | Z (across layers) is the weakest direction. Desktop PLA/PETG: Z ≈ 45–55% of in-plane strength. ASA/ABS lower. Fibre-filled and large-format worst. | PLA ~50% (63 vs 31 MPa). PETG 46%. ASA 29%. Typical 25–50% loss; 75–90% for fibre-filled | DUTY2018 (peer-reviewed, citing Shaffer, Torrado-Perez). CNCK-45. CNCK-MAT. STRATASYS-WP: upright impact 4–8 × lower. AHN2002. FR, SSD. | P | **b** + **a** | AGENTS.md: the main tension or bending stress must run in XY. State the expected load and the orientation in the report. Optional declared check **LoadDir** (§13): the script declares the stress direction of a feature (clip arm, hook, pin); **warn** when it is within 45° of Z. |
| S5 | Orient or split so loaded features run along the roads: snap arms flat, perimeters around bosses, horizontal pins. | — | AHN2002 rule 1. HUBS-FDM. PRUSA-MODEL. FICTIV-SNAP, FORMLABS-SNAP, HUBS-SNAP, SOVOL (snap arms). MF (split for strength). | — | **b** + **a** | As S4. |
| S6 | In-plane raster direction (±45 vs 0/90) changes strength. | 65–72% of molded for crisscross | AHN2002 only, for Stratasys FDM 1600 rasters | — | **d** | A slicer setting, not CAD. |

## 5. Bed edges, first layer, warping

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| B1 | The first layer flares (elephant's foot). The slicer compensates. | ≈0.15–0.2 mm on a 0.4 mm nozzle | PRUSA-EF ≈0.2 (on by default). ORCA-CFG BBL profile 0.15. CURA-DEF `xy_offset_layer_0`. BAMBU-XY lists it as a cause of size error. | P | **d** (slicer) + **b** | AGENTS.md: keep the CAD at nominal; elephant's foot is the slicer's job. The bed chamfer (O2) is for edges that must be clean and fit. |
| B2 | Chamfer size on bed edges. | 0.4–0.6 mm (forum only) | BAMBU-FORUM-WARP commenter. No primary source gives a size. **(1 src)** | — | **b** | Keep "~0.5–1 mm" as a default in AGENTS.md, labeled a convention rather than a sourced number. |
| B3 | ABS, ASA, PC and PA warp. They need an enclosure for large parts. PLA, PETG and TPU are "not prone to warping". Ranking: TPU ≈ PETG < PLA < ASA < ABS < PA. | — | PRUSA-WARP, PRUSA-MAT (ABS, ASA, PA, PETG, PLA, Flex), BAMBU-MAT, ORCA-WIKI brim (auto-brim sizes by material), HUBS-FDM, BOLAT2022 (peer-reviewed: ABS 0.8% short at 115 mm, PETG ≈0). | P | **b** + profile | New material field `warps = true` (abs, asa, pc, pa). Notes say "enclosure for parts over ~100 mm". Prusa's 10 × 10 cm ASA figure is (1 src), so it stays a note, not a threshold. |
| B4 | Warp mitigation by design: round the footprint corners, fillet vertical edges, avoid large solid flat areas, add ribs to large flat walls. | — | MF: fillet edges normal to the bed. FR: ribs on walls, fillet sharp corners. HUBS-KEY: ribs on large flat areas. HACKADAY-WARP: break up large footprints. BAMBU-FORUM-WARP: grooves 1 × 1 mm every 30–80 mm (community numbers, **1 src**). | P | **b** + **a** (hint) | AGENTS.md. **Warp** hint (automatic, **info** only): when the material has `warps` and the bed contact is over ~100 mm or has sharp corners under 2 mm radius, list them. Info only, because the thresholds are not sourced well enough to warn. |
| B5 | Brims, mouse ears, enclosure temperature. | Brim 4–18 mm | ORCA-WIKI, CURA-DEF, PRUSA-WARP | P | **d** | Slicer. Mention once in the report for warping materials. |
| B6 | A tall part on a small first layer is knocked over by the nozzle or wobbles: give it a brim or mouse ears, lay it down, or print several together. | auto brim = speed × H² × W / (1920 I); none under 5 mm, at most 18 mm; +5 mm for islands with area / perimeter < 1.1 mm over 10 mm tall | ORCA-BRIM (OrcaSlicer's Auto brim, the source code; Bambu Studio has the same: BAMBU-BRIM *(search text, not fetched)*, "a taller part with a smaller footprint usually needs a wider brim to prevent itself from being toppled by the printer's nozzle"). PRUSA-BRIM: a brim for "tall objects with a small base", "at least a 3 mm brim". Height:width rules of 5:1 or 10:1 appear only on a blog (SCIPEDIA), so none is used. | P | **a** (warn) + **b** | **tip-over** check (`TipOver`, automatic, warn only) with OrcaSlicer's measure at `tip_speed` (200 mm/s: OrcaSlicer's reference speed; Bambu's X1C profile moves up to 300); `suggest_orientation` scores the same measure. AGENTS.md: run `suggest_orientation` before export. |

## 6. Fits and clearances

| # | Rule | Value / range (per side unless noted) | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| F1 | Clearance ladder: press < alignment peg < sliding < free/moving. Values roughly double between printers. | press 0–0.15; peg 0.1–0.2; sliding 0.15–0.3; free 0.2–0.4 | UAL: Bambu H2D vs UltiMaker S7 tables, ~2× apart. SOVOL (vendor): press 0.05–0.15, slide 0.2–0.3. FICTIV-SNAP: 0.2 / 0.3 / 0.4 (side not stated). MF (diametral): press 0–0.05, close 0.05–0.1, free 0.1–0.2. Prusa forum: ~0.2. | P | **c** + **a** | **Fit coupon K2** measures press, slide and free values per printer and material. Calibration gets `clearance` (slide, existing) plus new `press_fit` and `free_fit`. New declared check **Gap** (§13) verifies the modeled gap between two assembly parts. |
| F2 | Moving parts: ≥0.3 mm (Prusa). Service bureaus use 0.4–0.5 mm, for unknown printers. | desktop 0.2–0.3; bureau 0.4–0.5 | PRUSA-MODEL ≥0.3 (side not stated). JLC 0.5. HUBS-SNAP 0.5. XOM-PRO 0.5. HLH 0.5. UZH 0.5. MAT 0.4. FORMLABS-JOINT, HUBS-JOINT 0.5 for interlocking joints. | P | **c** | The current default `CLEARANCE = 0.2` sits at the low end of the desktop range. Keep it, define it as **per side**, and let K2 measure it. |
| F3 | Print-in-place (parts printed assembled): ≥0.2–0.3 mm per side. 0.1–0.15 only on a tuned printer. | 0.2–0.3 | FAB24 (MK3S+: 0.1 fused, 0.2 moved). Prusa forum: 0.25 "easy". BAMBU-FORUM-PIP: 0.15 on default A1. SSD-2017: ≥1 line width in XY, ≥1 layer in Z. SOVOL 0.3–0.4 total. | P | **a** + **c** | **Gap**, automatic for multi-solid printable parts: a part made of several solids is print-in-place. **Fail** when two solids are closer than `pip_clearance` (default 0.3; K2 measures it): they would fuse. |
| F4 | State per side vs total for every clearance. | — | Most sources leave it ambiguous; UAL and OAK state it. | — | **b** | Already in AGENTS.md. Make it a defined term: `CLEARANCE` is per side. |
| F5 | Expected accuracy: ±0.2 mm (tuned desktop) to ±0.5% with a ±0.5 mm floor (prototyping bureau). | ±0.2 … ±0.5 | PRUSA-MODEL "at least 0.2". OAK 0.2. HUBS-STD and PL-FDM ±0.5% / 0.5 (prototyping), ±0.3% / 0.3 (industrial). XOM-PRO ±0.5% / 0.5. HLH ±0.3% / 0.3. JLC ±0.3 under 100 mm. MAT ±0.15% / 0.2. | P | **b** | AGENTS.md: don't design a fit that needs better than ±0.2 mm without a coupon. On parts over ~100 mm in a warping material (B3), mating features far apart drift. Locate them relative to each other. |

## 7. Snap fits and living hinges

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| N1 | Print snap arms flat, bending in XY, never with the arm along Z. If the arm must run along Z, halve the allowable strain. | — | FICTIV-SNAP (halve strain in Z). FORMLABS-SNAP (Z: −50% elongation, −20–30% strength). HUBS-SNAP. SOVOL (vendor). AHN2002 rule 1. | — | **b** + **a** | AGENTS.md. Optional declared **LoadDir** check (S4). |
| N2 | Root fillet ≥ 0.5 × arm thickness. | r ≥ 0.5 t | HUBS-SNAP, FICTIV-SNAP, SOVOL (vendor; min 0.8–1.0 at 0.4 nozzle). BASF/UL: "generous", no number. | — | **b** | AGENTS.md. A `snap_arm()` helper could build the root fillet in. |
| N3 | Taper the arm (thick at the root, thinner at the tip). | e.g. 100% → 50% | SOVOL, FICTIV-SNAP, FORMLABS-SNAP | — | **b** | AGENTS.md. |
| N4 | Size the arm with the cantilever strain formula and the material's allowable strain. | PLA 4–8%, ABS 7%, nylon 4–15%. No sourced PETG value | FICTIV-SNAP only, for FDM numbers. BASF/UL: the formula is valid for L/t > 10. **(1 src for the numbers)** | P | **b** (provisional) | AGENTS.md: use the formula and say it is an estimate. No material constants until a second source. A snap-fit coupon is a possible later addition. |
| N5 | L/t ratios: PLA 8–10, PETG 5–8. | — | SOVOL only | P | **b** (provisional) | (1 src, vendor blog). AGENTS.md, labeled provisional. |
| N6 | Snap-fit mating clearance. | 0.1–0.5 | FICTIV-SNAP 0.1–0.3. HUBS-SNAP 0.5. SOVOL 0.2–0.4 per side | P | **c** | K2 covers it. |
| N7 | Living hinge: 0.4–0.6 mm thick (≥2 layers). | 0.4–0.6 (up to 0.8) | HUBS-HINGE, FACFOX, 3ERP (~0.6). MH: molded 0.25–0.38 fails in FFF. | P | **b** | AGENTS.md. A hinge triggers ThinFeature (below min_wall), so ThinFeature needs a way to mark intentional thin regions (`ignore=` boxes or a `ThinOK(region, label)` declaration). |
| N8 | Living hinge material: nylon, TPU or PP. Not PLA or ABS. | — | MH, HUBS-HINGE, FACFOX, 3ERP | P | **b** + profile | AGENTS.md. PLA material notes already say "brittle in thin snap fits"; add "no living hinges". |
| N9 | Hinge orientation: build the hinge width along Z, so strands run across the hinge. | — | HUBS-HINGE, FACFOX, 3ERP | — | **b** | AGENTS.md. |
| N10 | Anneal hinges in hot water. | — | HUBS-HINGE only | — | **b** (provisional) | (1 src). AGENTS.md, labeled provisional. |

## 8. Threads, screws, inserts, nuts, bosses

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| T1 | Model threads only at M5–M6 and up. For smaller sizes use inserts, nuts or self-tapping. | ≥M5 (Hubs) / ≥M6 (JLC, Sovol) | HUBS-FAST, JLC, SOVOL (also: 0.1–0.2 mm per side thread clearance, thread axis along Z) | P | **b** | AGENTS.md. Modeled helical threads are hard to detect on the solid, so no check. |
| T2 | Heat-set inserts: use the insert maker's hole size, and compensate the hole like any other. | CNC Kitchen M3: hole 4.0, L 5.7, OD 4.6 | CNCK table (via 3DJAKE). CNCK-INS2: 4.2 in CAD gave easy seating at ~90% strength (= HOLE_COMP). PRUSA-INSERT: hole just big enough to push in. UWM: 0.2–0.4 under the OD. SOVOL: 0.1–0.3 under the knurl. | P | **b** + helper | Helper `insert_hole(size, maker="cnckitchen")`: the maker's table plus HOLE_COMP, depth L + 1. AGENTS.md: use it. |
| T3 | Insert blind hole ≈ insert length + ~1 mm. Install at print temperature +10–20 °C. | +1 mm; +10–20 °C | CNCK-TIPS (+1 mm; ~225 PLA / 245 PETG / 265 ABS). PRUSA-INSERT (+10 °C, elsewhere +10–20). UWM (+20 °C, deeper hole). SOVOL (+0.5–1.5 mm). | — | **b** | Depth in the helper. Temperature in the report's assembly notes. |
| T4 | Wall around an insert. | M2 1.3 / M3 1.6 / M4 2.1 / M5 2.6 / M6 3.3 (CNC Kitchen). SSD ≥2 mm (0.08 in). SOVOL ~2 mm. Hubs: wall = fastener diameter | CNCK table, SSD-2025, SOVOL, HUBS-FAST | P | **a** | The existing **Wall** check, with `min` from the helper's table (the CNC Kitchen minimum by default). The helper can return the matching Wall check. |
| T5 | Use inserts for repeated assembly. Screws driven into plastic hold in pull-out but not in torque (~1 Nm vs ~3 Nm). | — | CNCK-INS1 (142 kg pull-out, ~1 Nm direct). CNCK-HELI (insert 3 Nm, screw 1 Nm, nut ~2 Nm). FTC: plastic threads wear. | — | **b** | AGENTS.md: inserts or nuts for parts opened more than a few times. |
| T6 | Self-tapping / thread-forming pilot holes. | M3 ≈ 2.6–2.9 (by material and orientation). M4 into 3.3 | BAMBU-FORUM-SCREW (table). CNCK-INS1 (M3 in 2.7). FTC (M4 in 3.3). HUBS-FAST (75–80% engagement). UAL (−0.2–0 on diameter). | P | **c** + helper | Pilot-hole rows on the hole coupon (K1). Helper `pilot_hole(size, orientation)` with the calibrated value. |
| T7 | Captive hex nut pocket: across-flats + 0.2 mm total (0.1 per side). | +0.2 (b3dkit up to +0.3) | HUBS-FAST, OPENFLEX (M3 5.7 vs 5.5 nominal), B3DKIT | P | **b** + helper | Helper `nut_trap(size, axis)` with the sacrificial-bridge roof (O5) when the axis is vertical. |
| T8 | ≥3–4 perimeters around screw holes and inserts. Screws into low-infill regions miss material. | 3–6 perimeters | BAMBU-FORUM-SCREW (2 default, 3 self-tap). UWM (4). SOVOL (3–6). QIDI-BRACKET (≥3 mm boss, 4–6 walls). HUBS-SHELL (≥50% infill or more shell). PRUSA modifier blog (local modifiers). | P | **b** | AGENTS.md: give bosses enough wall for n perimeters, and list in the report which holes need more slicer perimeters. |

## 9. Text and fine detail

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| X1 | Embossed or engraved depth ≥ 0.5 mm (range 0.3–2). | 0.5 typical | XOM-PRO 0.5 / 0.5. HLH emboss 0.3, engrave 0.5. MAT engrave 0.3 / emboss 0.5. JLC 1.0. UZH 1.0. STAN 1.0. FORMLABS-FDM 2 (from Hubs). | P | **b** | AGENTS.md: ≥0.5 mm, a multiple of the layer height. Text on top (XY) surfaces. Note: `hole_coupon` labels are 0.4 mm deep (2 layers). Fine for a coupon; mention it. |
| X2 | Stroke width ≥ ~1 mm (≥ 2 line widths). | 0.5–2.5; ~1 typical | XOM-WEV 0.8–1.0. HLH 0.5. JLC 1.0. STAN 1.0. MAT 1.0 engrave / 2.5 emboss. | P | **a** | ThinFeature already measures strokes. Text below 2 lines gets the min-wall warning. |
| X3 | Character height ≥ ~5 mm (3.5 possible). Bold sans-serif. | 3.5–5 mm; 14–24 pt | XOM-PRO 3.5 capability / 5 recommended. HLH 14 pt. UZH 14 pt. OAK 16 pt top / 10 pt walls. SSD 24 pt bold monospace. | P | **b** | AGENTS.md. |

## 10. Corners, fillets, ribs

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| R1 | Fillet internal corners on loaded features. Sharp internal corners concentrate stress, worse across layers. | ≥0.5 mm (only Hubs gives a number) | SSD-2025, SSD-2017, HUBS-THIN (≥0.5), HUBS-ENCL, BIGREP (internal fillets matter more), PRINTEDSOLID, MF, UM | P | **b** | AGENTS.md: fillet internal corners of loaded features (snap roots N2, pin bases W5, brackets) ≥0.5 mm, and larger where there is room. No automatic check: every pocket corner would hit. |
| R2 | Outer bend radius = inner radius + wall, to keep the wall even. | — | SSD-2017 only | — | **b** (provisional) | (1 src). AGENTS.md, labeled provisional. |
| R3 | Outside vertical corners come out rounded at about nozzle scale. Never design knife edges. | ≈ line width / 2 | HUBS-FDM, XOM-WEB | P | **b** | AGENTS.md. ThinFeature flags knife edges as thin features. |
| R4 | Ribs and gussets: in FDM, do not thin them below the wall (no sink marks). ≥1.5 mm / ≥3 lines. | ≥1.5 mm | SSD-2025: not necessary to thin. XOM-MINI, XOM-WEB: 1.5 mm. *Disagree:* HUBS-ENCL 75–80%, HUBS-THIN 50–75% of wall (an injection-molding habit; Protolabs molding guide 60%). | P | **b** | AGENTS.md: ribs as thick as the wall. ThinFeature covers the minimum. No source gives rib height or spacing for FDM. |
| R5 | Use ribs to stiffen large flat walls and to fight warp. | — | FR, SSD, HUBS-KEY | — | **b** | With B4. |

## 11. Splitting parts and joints

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| J1 | Split when the part exceeds the build volume, needs a lot of support, or when pieces can each print in their strongest orientation. | — | PRUSA-CUT, SSD, FR, MF, HUBS-FDM, UM | P | **b** | AGENTS.md. The `fit` check already fails on build volume. Its message can point to splitting. |
| J2 | Joint types: dovetail for sectioned parts, dowels or alignment pins to locate, tongue and groove. Key joints stack up tolerance. | — | SSD-2025 (dovetail), PRUSA-CUT (plug / dowel / snap / dovetail), MF (dowels, shoulder bolts), FORMLABS-JOINT, HUBS-JOINT, DIGIKEY | — | **b** + helper | AGENTS.md. Later helpers `dovetail()` / `dowel_pair()` that apply the calibrated clearance. |
| J3 | Joint clearance. | 0.1–0.5 (range) | FORMLABS-JOINT 0.5. HUBS-JOINT 0.5. MF 0.05–0.2 total. SSD-2017: ≥1 line width. | P | **c** | K2. |
| J4 | Glue by material: CA bonds all common filaments. Acetone welds ABS/ASA (and PLA). PETG has no hobby solvent, so use CA or epoxy. | — | PRUSA-GLUE, PRUSA-MAT (ASA), FORMLABS-JOINT, XOM-WEB | P | **b** + profile | Add a `glue` line to the material notes. |
| J5 | Glued joints are weaker than the parent material. CA is weak in peel and torsion. | CA ≈ 9–13 MPa (quick test) | PRUSA-GLUE, DIGIKEY | — | **b** | AGENTS.md: a glued joint needs a mechanical key (dovetail or pins). |

## 12. Shrinkage and other material effects

| # | Rule | Value / range | Evidence | P | Class | Proposed behavior |
|---|---|---|---|---|---|---|
| M1 | Shrinkage is mostly in XY and depends on the material. Compensate in the slicer per filament and keep the CAD at nominal. Holes need separate compensation. | — | BAMBU-SHRINK, UM, SSD (no shrink in design), GRABCAD | P | **b** | AGENTS.md: CAD stays nominal, and HOLE_COMP is separate. |
| M2 | Shrinkage percentages. | PLA ~0.3, PETG ~0.4, ASA ~0.7, ABS ~0.8, PA 1–3 % | Calculator pages only (PRINTFARMCALC, GRANDPACAD). BOLAT2022 is consistent for ABS/PETG. No filament maker publishes them. | P | **d** | Not authoritative. Do not encode. |
| M3 | Tiny layers (pins, spires) are slowed by minimum layer time and sag. Seams hide in sharp corners. | — | PRUSA-COOL, ORCA-WIKI cooling. PRUSA-SEAM, ORCA-WIKI seam. | — | **d** | Slicer. (A seam groove on cosmetic cylinders is a possible AGENTS.md tip; low value.) |

---

## 13. Checks

The automatic checks run for every printable part, like `fit`. They take their limits from the
settings (printer profile, calibration), and a part script changes or narrows one by listing it
in `checks(d)` (for example `ThinFeature(part, ignore=[box])`). See
[The checks](using/checks.md) and the [Checks API](scripts/checks-api.md).

| Check | Rules | How it is measured | Result |
|---|---|---|---|
| **thin** (`ThinFeature`, automatic) | W1, W2, X2, R3 | Sections on XY, XZ and YZ: one between each pair of neighbouring flat faces parallel to the plane (a 0.6 mm label gets its own cut) and every 2 mm in between. `wall_thickness()` on each whole section, only looking for walls under the limit. A spot counts as a wall when it is thin in at least two of the three planes through it; otherwise it is a knife edge (a taper or the tip of a corner). `ignore=` boxes for regions thin on purpose (hinges, labels). | wall **fail** < 1 line width (0.45 generic, else the printer's), **warn** < `min_wall`; knife edges **warn** |
| **holes** (`Holes`, automatic) | H3, H5 | Concave cylindrical faces grouped by axis and radius, covering ≥ 260° (a full hole or a teardrop; fillets and arches cover less). A non-vertical hole has a "round top" when part of its wall faces down steeper than `max_overhang`. | **warn** round-topped horizontal hole d ≥ 2 mm; **warn** d < 1 mm |
| **overhang** with bridges (`Overhang`, automatic) | O1, O3, O4 | Flat downward faces: from a grid of points, 24 rays find the face boundary; a point is bridged when two opposite rays end on anchored edges, its span is their sum. An edge is anchored when there is material just beyond and below it, or the next face continues tangentially and curves down. | bridge span > `max_bridge` **warns** (never fails); a cantilever is an overhang (fails with `fail=True`) |
| **bed edge** (`BedEdge`, automatic) | O2 | Curved faces starting on the bed whose lower part faces down steeper than `max_overhang`. | **warn** |
| **tip-over** (`TipOver`, automatic) | B6 | The first layer is the MeshSlicer section half a layer above the bed. Its area and second moment of area about its principal axes (the narrowest width and across it when the two are equal) give OrcaSlicer's auto-brim width at `tip_speed`; the islands' area / perimeter; the centre of mass against the footprint's convex hull. | **warn** brim estimate ≥ 5 mm, a strip island, or the centre of mass outside; parts under 10 mm skipped |
| **gap** (`Gap`, automatic for parts of several solids; declared for assemblies) | F1, F3 | `distance_to` (BRepExtrema) between the solids of one part or between two parts, optionally inside a box. | automatic: **fail** < `pip_clearance`; declared `Gap(a, b, min=, max=)`: fail outside the range |
| **wall** (`Wall`, declared) | T4 | Existing: thinnest wall around one cut. | **fail** < `min` |

Each check is tested on shapes with known answers in `tests/test_checks.py`: a 0.3 mm fin, plate
and pin fail, a 0.6 mm wall warns, a 15° wedge is a knife edge; a round horizontal hole warns
and its teardrop passes; a 30 mm tunnel roof is a 30 mm bridge, a closed pocket bridges the short
way and a ledge off one wall is a cantilever; a filleted bed edge warns and a chamfered one
passes; two solids 0.1 mm apart fail.

**Not yet implemented** (plan P3): W5, W6, S4, S5, N1, B4. The guidance for them is in AGENTS.md.

## 14. Calibration coupons

| Coupon | Measures | Rules | Result stored |
|---|---|---|---|
| **`hole_coupon`** | Vertical holes 2–8 mm; on an upright tab, horizontal holes 3–8 mm, round (lower row) and teardrop (upper row). | H1, H4 | `hole_comp`, `hole_comp_h` |
| **`fit_coupon`** | A 6 mm peg and holes at 0–0.40 mm per side (press / slide / free); discs printed inside rings at 0.10–0.40 mm. | F1, F2, F3, N6, J3, W7 | `press_fit`, `clearance`, `free_fit`, `pip_clearance` |
| **`overhang_bridge_coupon`** | Ledges at 40–75° from vertical; bridges of 5–40 mm. | O1, O3 | `max_overhang`, `max_bridge` |

All three pass `b123d-print check` (with the warnings they exist to show). Each one's docstring
says how to read it and where the number goes: `b123d-print printer calibrate <key> <value>` for
the active printer + material, or the user config. Insert holes (T2) need no row of their own:
the maker's size plus `hole_comp`. Pilot holes for self-tapping screws (T6) stay guidance until
a helper uses a measured value (P3).

## 15. Settings

- **Printer profile:** `max_bridge` (default 10 mm).
- **Settings and calibration** (per printer + material, `calibration.toml`): `hole_comp`,
  `hole_comp_h` (defaults to `hole_comp`), `press_fit` (0.05), `clearance` (0.2, sliding),
  `free_fit` (0.3), `pip_clearance` (0.3), `max_overhang`, `max_bridge`.
- **Definitions:** `clearance` and every fit value are **per side**.
- Not yet (P3): a material `warps` field and glue/hinge notes.

## 16. Keeping the knowledge right

1. **This page is the source of truth.** Every rule has an ID (W1, H3, …) and the sources
   behind it.
2. **Code and guidance cite IDs**: `BP-H3` in code, `[H3]` in AGENTS.md. `tests/test_rules.py`
   fails when:
   - code or AGENTS.md cites an ID that is not here, or one classed **d**;
   - a class-**a** rule has no check citing it and is not on the "not yet implemented" list;
   - a class-**b** rule is missing from AGENTS.md;
   - a class-**c** rule is cited neither in AGENTS.md nor by a coupon.
3. **Checks are tested on known geometry** (§13).
4. **Printer-dependent numbers are measured, not assumed.** The coupons turn them into the
   user's own calibration; the defaults sit at the conservative end of the sourced range.
5. **The eval harness** can score agents' parts against these checks, which tests whether the
   guidance changes what agents draw.
6. **Re-verify now and then**: re-fetch the URLs, and have a person re-read a claim when its
   page changes.

## 17. Implementation plan and status

**P1 (done).** `ThinFeature` (W1, W2, X2, R3), `Holes` (H3, H5), bridge span and cantilever
ceilings in `Overhang` (O3, O4) with `max_bridge`, `BedEdge` (O2), AGENTS.md rules with IDs, and
the rule-ID test.

**P2 (done).** `Gap` (F1, F3), `fit_coupon`, `overhang_bridge_coupon`, `hole_coupon` v2, and the
calibration keys (`hole_comp_h`, `press_fit`, `free_fit`, `pip_clearance`, `max_overhang`,
`max_bridge`) with `b123d-print printer calibrate`.

**P3 (not yet).**
- Helpers: `teardrop_hole()`, `insert_hole()` (CNC Kitchen table + HOLE_COMP + matching Wall
  check), `nut_trap()`, `pilot_hole()`, `snap_arm()`.
- Checks: **Pins** (W5, W6), **LoadDir** (S4, S5, N1), **Warp** hint (B4).
- Material `warps` / glue notes.

**Dropped:** the class-d rows: slicer tuning, shrinkage percentages, rib ratios borrowed from
injection molding.

## 18. Decisions (review of 2026-10-17)

1. ThinFeature fails below one line width and warns below `min_wall`.
2. Bridges warn above 10 mm (`max_bridge` default) until the coupon is printed.
3. Clearances are per side: 0.2 sliding (`clearance`), 0.3 for moving parts (`free_fit`) and
   parts printed in place (`pip_clearance`).
4. Bed edges: "chamfer, not fillet"; BedEdge warns.
5. Helpers: later (P3).
6. Single-source rules are in AGENTS.md, labeled provisional with their one source; they never
   become checks or default constants.

---

## Sources

These are the
URLs, grouped by publisher. *(vendor)* = a seller's blog. *(community)* = forum, course or
hobby page. *(peer-reviewed)* = journal or conference.

**Prusa**

- PRUSA-MODEL: https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135
- PRUSA-LP: https://help.prusa3d.com/article/layers-and-perimeters_1748
- PRUSA-ARACHNE: https://help.prusa3d.com/article/arachne-perimeter-generator_352769
- PRUSA-EF: https://help.prusa3d.com/article/elephant-foot-compensation_114487
- PRUSA-SUP: https://help.prusa3d.com/article/support-material_1698
- PRUSA-WARP: https://help.prusa3d.com/article/warping_2011
- PRUSA-BRIM: https://help.prusa3d.com/article/skirt-and-brim_133969
- PRUSA-INFILL: https://help.prusa3d.com/article/infill_42
- PRUSA-CUT: https://help.prusa3d.com/article/cut-tool_1779
- PRUSA-COOL: https://help.prusa3d.com/article/cooling_127569
- PRUSA-SEAM: https://help.prusa3d.com/article/seam-position_151069
- PRUSA-MAT:
  - https://help.prusa3d.com/article/abs_2058
  - https://help.prusa3d.com/article/asa_1809
  - https://help.prusa3d.com/article/petg_2059
  - https://help.prusa3d.com/article/pla_2062
  - https://help.prusa3d.com/article/polyamide-nylon_167188
  - https://help.prusa3d.com/article/flexible-materials_2057
- PRUSA-GLUE: https://blog.prusa3d.com/the-great-guide-to-gluing-and-assembling-3d-prints_44908/
- Prusa modifier meshes: https://blog.prusa3d.com/model-with-prusaslicer-modifier-meshes-tutorial_30438/
- PRUSA-INSERT: https://www.prusa3d.com/en/product/heat-set-inserts-m3-standard-100-pcs/
- Prusa forum *(community)*: https://forum.prusa3d.com/forum/prusa-core-one-hardware-firmware-and-software-help/what-are-the-minimum-reliable-printing-distances

**Bambu Lab**

- BAMBU-XY: https://wiki.bambulab.com/en/software/bambu-studio/xy-hole-contour-compensation
- BAMBU-AUTO: https://wiki.bambulab.com/en/software/bambu-studio/manual/auto-circle-contour-compensation
- BAMBU-SHRINK: https://wiki.bambulab.com/en/knowledge-sharing/3d-prints-shrinkage
- BAMBU-MAT: https://wiki.bambulab.com/en/general/filament-guide-material-table
- BAMBU-FORUM-SCREW *(community; MakerWorld account)*: https://forum.bambulab.com/t/how-to-design-screw-holes-for-3d-printing/217352
- BAMBU-FORUM-WARP *(community)*: https://forum.bambulab.com/t/large-prints-say-goodbye-to-warping/240898
- BAMBU-FORUM-PIP *(community)*: https://forum.bambulab.com/t/print-in-place-hinge-tolerances/111715
- SCIPEDIA *(blog, uncited)*: https://sciencepedia.blog/3d-print-tall-thin-objects-stability-guide

**Slicers and modeling tools**

- ORCA-CFG: https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/PrintConfig.cpp and the BBL profile https://github.com/SoftFever/OrcaSlicer/blob/main/resources/profiles/BBL/process/fdm_process_single_0.20.json
- ORCA-WIKI:
  - https://github.com/SoftFever/OrcaSlicer/wiki/quality_settings_precision
  - https://www.orcaslicer.com/wiki/print_settings/quality/quality_settings_overhangs.html
  - …/quality_settings_bridging.html
  - …/support/support_settings_support.html
  - …/support/support_settings_advanced.html
  - …/others/others_settings_brim.html
  - …/material_settings/cooling/material_cooling
  - …/quality/quality_settings_seam
- ORCA-BRIM: https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/Brim.cpp (`configBrimWidthByVolumeGroups`; the additional brim for small islands) and https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/Model.cpp (`get_auto_brim_width`, reference speed 200); speeds: https://github.com/SoftFever/OrcaSlicer/blob/main/resources/profiles/BBL/process/fdm_process_single_0.20.json
- BAMBU-BRIM: https://wiki.bambulab.com/en/software/bambu-studio/auto-brim
- CURA-DEF: https://github.com/Ultimaker/Cura/blob/main/resources/definitions/fdmprinter.def.json
- SLIC3R: https://manual.slic3r.org/troubleshooting/dimension-errors
- OPENSCAD: https://app.openscad.org/documentation/manual/undersized_circular_objects.html
- NOPHEAD: https://hydraraptor.blogspot.com/2011/02/polyholes.html
- B3DKIT *(community)*: https://b3dkit.readthedocs.io/en/latest/bolt_fittings/

**Design guides (service bureaus and printer makers)**

- Hubs / Protolabs Network:
  - HUBS-FDM: https://www.hubs.com/knowledge-base/how-design-parts-fdm-3d-printing/
  - HUBS-KEY: https://www.hubs.com/knowledge-base/key-design-considerations-3d-printing/
  - HUBS-SNAP: https://www.hubs.com/knowledge-base/how-design-snap-fit-joints-3d-printing/
  - HUBS-HINGE: https://www.hubs.com/knowledge-base/how-design-living-hinges-3d-printing/
  - HUBS-FAST: https://www.hubs.com/blog/knowledge-base/how-assemble-3d-printed-parts-threaded-fasteners
  - HUBS-THIN: https://www.hubs.com/knowledge-base/dfm-tips-for-3d-printed-parts-with-thin-walls/
  - HUBS-ENCL: https://www.hubs.com/knowledge-base/enclosure-design-3d-printing-step-step-guide/
  - HUBS-JOINT: https://www.hubs.com/knowledge-base/how-design-interlocking-joints-fastening-3d-printed-parts/
  - HUBS-SHELL: https://www.hubs.com/knowledge-base/selecting-optimal-shell-and-infill-parameters-fdm-3d-printing/
  - HUBS-STD: https://hubs.com/manufacturing-standards
- PL-FDM (Protolabs): https://www.protolabs.com/services/3d-printing/fused-deposition-modeling/
- Formlabs:
  - FORMLABS-FDM: https://formlabs.com/blog/fdm-3d-printing-design-guide/
  - FORMLABS-SNAP: https://formlabs.com/blog/designing-3d-printed-snap-fit-enclosures/
  - FORMLABS-JOINT: https://formlabs.com/blog/how-to-3d-print-interlocking-joints/
- Xometry (one publisher):
  - XOM-PRO: https://xometry.pro/en/?p=154421
  - XOM-MINI: https://xometry.com/blog/fdm-mini-guide (also https://www.xometry.com/resources/3d-printing/mini-guide-fdm-3d-printing/)
  - XOM-WEV: https://www.wevolver.com/article/fdm-3d-printing-design-tips-best-practices-and-techniques-for-stronger-prints
  - XOM-WEB: https://www.xometry.com/resources/blog/expert-3d-printing-design-tips-webinar/ and https://www.machinedesign.com/3d-printing/best-practices-fdm-3d-printing
- Stratasys Direct (one publisher):
  - SSD-2025: https://www.stratasys.com/siteassets/sdm/content---website-storage/design-guides/dg_sdm_fdm_0725a.pdf
  - SSD-2017: https://www.secs.oakland.edu/~latcha/ME4999/fdm_design_guidelines_2017-1.pdf
  - GRABCAD: https://grabcad.com/tutorials/fused-deposition-modeling-fdm-design-guidelines
- STRATASYS-WP: https://prod-cms.stratasys.com/siteassets/resources/white-papers/unidirectional-material-testing-may-mislead-manufacturing/wp_beyond-the-data-sheet--unidirectional-material-testing--may-mislead-manufacturing_0723.pdf
- UM (UltiMaker): https://ultimaker.com/wp-content/uploads/2024/06/How-to-design-for-FFF-1.pdf
- MF (Markforged): https://static.markforged.com/downloads/CompositesDesignGuide.pdf
- FR (Fast Radius): https://www.fastradius.com/wp-content/uploads/2022/04/fdm-dfm-design-guide.pdf
- Other service bureaus:
  - HLH: https://hlhrapid.com/knowledge/design-guide-fdm-3d-printing/ and https://hlhrapid.com/knowledge/3d-printing-design-guide-adding-text-lettering-and-symbols/
  - JLC: https://jlc3dp.com/help/article/3D-Printing-Design-Guideline
  - MAT (Materialise): https://www.materialise.com/en/academy/industrial/design-am/abs-m30
  - FACFOX: https://facfox.com/docs/kb/fdm-3d-printing-design-tips and https://facfox.com/docs/kb/how-to-design-living-hinges-for-3d-printed-parts
  - 3ERP: https://www.3erp.com/design-tips/how-to-design-living-hinges-for-injection-molding-or-3d-printing/
  - POLLEN: https://www.pollen.am/design_for_3d_printing_holes
- FICTIV-SNAP: https://www.fictiv.com/articles/how-to-design-snap-fit-components
- BIGREP: https://bigrep.com/posts/fillets-vs-chamfers-in-3d-printed-parts/
- MH (MatterHackers): https://www.matterhackers.com/news/living-hinge:--design-guidelines-and-material-selection
- BASF via UL Prospector: https://ulprospector.ul.com/1248/snapfit-3/

**Universities**

- UZH: https://www.amf.uzh.ch/dam/jcr:fd1ee024-1a98-488b-89ec-ffd85befa786/Design-Guideline-FDM.pdf
- OAK: https://www.secs.oakland.edu/~latcha/me492/3Dprinting.html
- STAN: https://lab64.stanford.edu/hiddenoutdated-items/fdm-rules-of-thumb
- UWM: https://medesignlab.me.wisc.edu/?p=162
- UAL: https://wiki.cci.arts.ac.uk/books/digital-fabrication-lab/page/design-the-clearance-and-tolerance-readme

**Tests and papers**

- CNC Kitchen:
  - CNCK-INS1: https://www.cnckitchen.com/blog/threaded-inserts-for-3d-prints-cheap-vs-expensive
  - CNCK-INS2: https://www.cnckitchen.com/blog/are-our-heat-set-insert-datasheets-wrong
  - CNCK-TIPS: https://www.cnckitchen.com/blog/tips-and-tricks-for-heat-set-inserts
  - CNCK-HELI: https://www.cnckitchen.com/blog/helicoils-threaded-insets-and-embedded-nuts-in-3d-prints-strength-amp-strength-assessment
  - CNCK-45: https://www.cnckitchen.com/blog/stop-printing-flat-the-45-secret-for-stronger-parts
  - CNCK-MAT: https://www.cnckitchen.com/blog/comparing-pla-petg-amp-asa-feat-prusament
  - CNCK-NOZ: https://cnckitchen.com/blog/big-nozzles-how-do-they-make-your-3d-prints-stronger
  - CNCK-EW: https://www.cnckitchen.com/blog/the-effect-of-extrusion-width-on-strength-and-quality-of-3d-prints
  - CNCK-BEG: https://www.cnckitchen.com/blog/the-beginner-3d-printing-guide-i-wish-i-had
  - CNC Kitchen insert table (via 3DJAKE): https://www.3djake.com/cnc-kitchen/threaded-inserts-m3-standard
- AHN2002 *(peer-reviewed)*: Ahn et al., Rapid Prototyping J. 8(4) 2002, https://iss.mech.utah.edu/wp-content/uploads/sites/103/2012/10/Ahn-Anisotropic_material-2002.pdf
- DUTY2018 *(peer-reviewed, SFF Symposium)*: https://utw10945.utweb.utexas.edu/sites/default/files/2018/198%20ZPinningApproachforReducingMechanicalAnisotr.pdf
- PANICO2026 *(peer-reviewed)*: DOI 10.4028/p-afh2mu, https://iris.unime.it/handle/11570/3356830
- BOLAT2022 *(peer-reviewed)*: https://muhendislik.cu.edu.tr//storage/Dergi/37-2-2022/14.pdf

**Community, vendor and other pages**

- FAB22 *(community)*: https://fabacademy.org/2022/labs/opendot/group-assignments/week06.html
- FAB24 *(community)*: https://fabacademy.org/2024/labs/reykjavik/assignments/week05.html
- OPENFLEX *(community)*: https://gitlab.com/openflexure/openflexure-microscope/-/merge_requests/371
- FTC: https://ftc-docs.firstinspires.org/manufacturing/3d_printing/designing_and_slicing/working_with_screws/working_with_screws.html
- HACKADAY-SB: https://hackaday.com/tag/sacrificial-bridge/
- HACKADAY-WARP: https://hackaday.com/2026/09/03/corners-lifting-on-3d-prints-guide-gives-prevention-tips/
- WEVOLVER-OH: https://wevolver.com/article/3d-print-overhang
- 3DMAG: https://www.3dmag.com/3d-wikipedia/3d-printing-bridging-settings-materials-and-limits/
- QIDI-BRIDGE *(vendor)*: https://qidi3d.com/blogs/news/3d-printing-bridging-explained-from-problem-to-solution
- QIDI-BRACKET *(vendor)*: https://qidi3d.com/blogs/print-lab/3d-printed-shelf-brackets-load-capacity-design
- SOVOL *(vendor)*:
  - https://www.sovol3d.com/blogs/news/fdm-3d-printing-tolerances-clearances-how-to-design-parts-that-fit
  - …/3d-printed-snap-fit-joints-how-to-design-clips-that-work
  - …/3d-printing-threads-and-screws-how-to-design-reliable-fdm-fasteners
  - …/3d-printing-with-heat-set-inserts-design-strong-screw-bosses-that-last
- PRINTEDSOLID *(vendor)*: https://www.printedsolid.com/blogs/news/37036739-3d-printing-design-tips-part-1-stress-concentrations
- DIGIKEY: https://www.digikey.com/en/maker/blogs/2024/how-to-split-and-join-large-3d-prints
- PRINTFARMCALC: https://printfarmcalc.com/reference/shrinkage/
- GRANDPACAD: https://grandpacad.com/en/tools/material-shrinkage-calculator

**Unreachable or gated** (not used as sources):

- Pages that returned errors:
  - Protolabs FDM design-guideline pages (404)
  - Xometry FDM design guide (404 or gated)
  - Hubs threads page (404)
  - Hubs dimensional-accuracy page (404)
  - All3DP (403)
  - Markforged support articles (401/403)
  - UltiMaker support web pages (did not render; the Cura source and the UltiMaker PDF were used instead)
  - PlasticsToday / DesignNews snap-fit articles (403)
  - TriMech splitting tips (403)
  - MATEC 2017 shrinkage paper (403)
  - OrcaSlicer tolerance-calibration page (404)
  - Reiman FDM guidelines PDF (403)
- Gated documents:
  - BASF snap-fit strain table (figures only)
  - Formlabs snap-fit white paper
- Read only as an abstract, so its values were not used: the 2024 Adv. Mater. Res. 1180 paper on stress concentration factors (Kt) vs fillet radius in PLA.
- PrusaSlicer `PrintConfig.cpp` (404 at the path tried): no PrusaSlicer default values were read from source.
