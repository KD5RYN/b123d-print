# How a session goes

Start with one of the [MCP prompts](tools.md#prompts) where your client supports them —
**`design_part_from_photos`**, **`modify_part`**, **`verify_part`**, **`calibrate_hole_comp`** —
or just ask; the server's instructions and the `b123d-print://guide` resource carry the same
rules ([Workflow rules](../scripts/rules.md)). An illustrative, shortened exchange:

> **You:** A case for this PIR sensor, mounted on a wall outside. *(photos with calipers)*
>
> **Model:** Dimensions I read: body 69.6 × 24.5 × 19.1 (photo 2, calipers), dome Ø18.6
> (photo 3), dome center about 35.5 from the bottom (estimate). Nothing shows how far the dome
> sticks out. Please confirm or correct before I model.
>
> **You:** Dome sticks out 8. The rest is right.
>
> **Model:** *(new_part, write_part, build_part, render_preview, three sections, check; fixes a
> thin wall the check found, checks again)* Done: 35.1 × 38.8 × 76.6 mm, valid. The sensor gets
> 0.6 mm per side, the dovetail 0.2 per face. Prints on its floor without supports (one flat
> bridge over the groove). Exported 3MF and PNG.

## What to expect

1. **Dimensions first.** The model lists every dimension it read from your photos and text, the
   features that have none, and any conflicts, then waits. Typed numbers win over photo readings.
2. **One script per part.** Every dimension is a named field you can change later; variants
   (a bigger one, a tilted one) live in the same script. See [The part script](../scripts/convention.md).
3. **Verified before it reports.** Build, preview render, sections through every mating
   feature, and [the checks](checks.md) — and it fixes what fails.
4. **A report** with the overall size, key dimensions, the clearance and hole compensation
   applied, check results, print orientation and any supports needed.
5. **A fit test first, if it mates with something.** For a part that sits on a board, a wall or
   another part, or has a hole pattern, the model offers a [fit-test template](templates.md): a
   thin print of a face, slice or region of the real part, minutes instead of hours. It shows you
   the face or region in red before making it.
6. **A design review, if you want one.** Once the checks pass, the model can review the part for
   the style you chose (functional, modern, least cost, rugged, soft, structural, or your own) and suggest
   changes with rough filament and time numbers. It changes nothing without your OK. See
   [Design review](design-review.md).

!!! note
    The model can only look at its renders if your client passes tool-result images to the
    model (see [Quick start](../getting-started/quick-start.md)).
