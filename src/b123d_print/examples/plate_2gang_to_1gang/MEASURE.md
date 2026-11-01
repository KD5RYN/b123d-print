# plate_2gang_to_1gang: measurements and replication spec

A copy of an injection-molded 2-gang to 1-gang adapter plate, made printable. The original's
drawing is `ref/original_drawing.png`; `replication_spec` (CLI `b123d-print spec`) joins this
table with the script's `Dims`.

- **Units:** mm (the screw spacings are standard inch sizes, converted)
- **Datum:** the plate's centre (X, Y) and its front face (Z)
- **Orientation:** in use the front faces the room; it prints front face down
- **Must fit:** a 2-gang box (4 × #6-32 pan-head screws in the corner holes, heads below the
  face) and a 1-gang smart switch (2 × 6-32 screws into the centre holes; the switch passes
  through the opening)
- **Original:** molded, material unknown (glossy white). Cored back: a 2.4 face, a 6.5 rim, an
  inner frame rim with a row of small screw bosses for other box and device patterns
- **Accuracy:** calipers, ±0.05 on hard edges and holes, ±0.1 on the outline and depths

| Feature | Value | Method | Accuracy | Status | Class | Source | Field | Why changed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Box screw spacing, vertical | 83.3 (3-9/32 in, NEMA WD-6) | standard (NEMA WD-6) | ±0.2 | CONFIRMED | critical | standard | BOX_SCREW_SPACING_Y | |
| Gang spacing, horizontal | 46.0 (1-13/16 in) | standard (NEMA WD-6) | ±0.2 | CONFIRMED | critical | standard | GANG_SPACING_X | |
| Device screw spacing | 83.3 (3-9/32 in) | standard (NEMA WD-6) | ±0.2 | CONFIRMED | critical | standard | DEVICE_SCREW_SPACING_Y | |
| Box screw hole Ø | 3.7 | calipers, inside jaws, rocked | ±0.05 | CONFIRMED | critical | measured | CORNER_HOLE_D | |
| Counterbore Ø | 7.3 | calipers, inside jaws | ±0.05 | CONFIRMED | critical | measured | CBORE_D | |
| Counterbore depth | 2.5 | calipers, depth rod | ±0.1 | CONFIRMED | critical | measured | CBORE_DEPTH | |
| Device screw hole Ø | 2.8 | calipers, inside jaws, rocked | ±0.05 | CONFIRMED | critical | measured | CENTER_HOLE_D | |
| Opening width | 52.5 | calipers, inside jaws | ±0.1 | CONFIRMED | critical | measured | OPENING_W | |
| Opening height | 73.8 | calipers, inside jaws | ±0.1 | CONFIRMED | critical | measured | OPENING_H | |
| Notch depth past the opening edge | 1.3 | calipers, depth rod | ±0.1 | CONFIRMED | free | measured | NOTCH_DEPTH | |
| Notch width | ~6 | read from a photo | ±1 | estimated | free | estimate | NOTCH_W | |
| Plate width | 125.0 | calipers, outside jaws | ±0.1 | CONFIRMED | free | measured | PLATE_W | |
| Plate height | 125.0 | calipers, outside jaws | ±0.1 | CONFIRMED | free | measured | PLATE_H | |
| Front face to back of the rim | 6.5 | calipers, depth rod | ±0.1 | CONFIRMED | free | measured | PLATE_DEPTH | |
| Face thickness | 2.4 | calipers, outside jaws through the opening | ±0.05 | CONFIRMED | free | measured | FACE_T | |
| Inside of the rim | 120.3 | calipers, inside jaws | ±0.1 | CONFIRMED | free | measured | PLATE_W - 2 * RIM_WALL | |
| Outer corner radius | ~3 | read from a photo | ±1 | estimated | free | estimate | CORNER_R | |
| Bosses and inner frame, from the face | 4.3 | calipers, depth rod | ±0.1 | CONFIRMED | free | measured | BOSS_DEPTH | |
| Wall around each corner counterbore | | | | | free | changed | BOSS_WALL | the molded boss is thin; 2.0 min wall in the copy: its first print broke through a 0.05 mm skin there |
| Inner frame rim around the opening | | photos | | | free | changed | INNER_RIM_W | cored molded frame replaced by a solid frame around the opening, tying the bosses together |
| Back coring and the extra screw bosses | | photos | | | free | changed | RIB_W | the extra bosses (other box patterns) are dropped; straight ribs to the rim stiffen the face instead of the molded coring |
| Front perimeter edge | | photos | | | free | changed | FRONT_EDGE_FILLET | the molded edge is rounded; R3 keeps that look on the face that prints down |
