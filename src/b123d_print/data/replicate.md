| Molded feature | Why the mold has it | In the printed copy | Rule |
| --- | --- | --- | --- |
| Draft (faces taper along the mold's opening; molded 0.5–2°, more under texture) | so the part releases | remove it; keep a taper only where it does a job (a taper fit, parts that nest or stack) or is part of the look. Measure a drafted wall where it mates, or at mid-height, and say which | C1, C2 |
| Thin even walls, coring (molded walls ~2–4 mm, thick areas hollowed) | to fill and cool evenly without sink | solid, or thicker walls in whole line widths; keep a cored pocket only where it does a job (weight, clearance, a mating feature) | C3 |
| Ribs and gussets (molded 40–60 % of the wall) | stiffness without sink | keep where they run (the stiffening intent) at full wall thickness, or drop them where solid replaces them | C4 |
| Sink marks, parting line and flash, ejector-pin marks, gate vestige, knit lines | marks of the molding | never model them or measure on them; a sink shows a thick section behind it; a crack on a knit line is a molding weakness | C5 |
| Living hinge (PP or PE, 0.2–0.35 mm, a million cycles) | PP flexes for ever | cannot be copied: 0.4–0.6 mm in nylon, TPU or PP with the hinge width along Z (tens of cycles), or a pin or print-in-place hinge | C6 |
| Snap fit (sized for POM, PP, nylon) | molded resins take high strain | recompute the arm for the print material's strain (the snap_arm recipe), print it flat, ~60 % of the strain for snaps opened often | C7 |
| Screw bosses, self-tapping holes, molded threads, inserts | sized for sink and molding | the position and the screw, not the molded proportions: thicker wall and gussets; a heat-set insert or nut for screws taken out often; threads modeled only at M5–M6 and up; declare the screw as hardware | C8 |
| Material (PP, POM, PA, ABS, PC) | chosen for strain, heat, creep, chemicals or sunlight | pick the print material by that property: strain or a hinge → PETG, nylon, TPU or a redesign; heat → ASA, PC, PA (PLA softens near 55–60 °C, molded PP ~80–85, POM ~110); outdoors → ASA; sliding → nylon. The copy is weaker across its layers: put the load along them and say so | C9 |
| Mold shrinkage | the mold was cut oversize | none: the part is already at nominal size, so model what you measure; FDM shrinkage is the slicer's | C12 |
| Extra bosses, knock-outs, features for other models of the product | one mold serves several products | drop what this copy does not use; say so in Why changed | C10 |

Measuring a part to copy: one datum, not chained; the design intent (what fits and works), not the
as-built shape; threads by major diameter and pitch against a chart; a worn or broken part measured
on its unworn areas and the mating part [C10]. Provisional (one source): round a reading to the
value the designer meant (43.97 → 44 mm, inch vs mm, standard sizes) and say so [C11].
