# Building a CS2 glove procedurally, from one listing image

The steps that actually produced geometry, in the order that worked, with the traps that cost the most
time. Refined across ~20 review rounds on Hydra Gloves | Case Hardened; the artefacts are under
`.img2threejs/hydra-ch-v1/` and the reusable code under `runtime/glove-procedural/`.

**A different glove is a different spec object, not different code.** `runtime/glove-procedural/glove.mjs`
is the builder and `shell-sdf.mjs` is the organic shell; one item's measurements live in one spec module
(the worked example is `.img2threejs/hydra-ch-v1/viewer/hydra-case-hardened.mjs`). Copy the spec, never
the builder. Every hard part is optional in the spec — `knucklePlate`, `hydra` (emblem), `spikes`,
`cuff.elastic`, `cuff.strap`, `palmarPanels` — so the same builder serves moto, specialist, sport,
driver and broken-fist subtypes by omission, not by forking.

---

## Why this does not go through `generate_threejs_factory.py`

Two properties of the generator make it unable to build a glove, and both are load-bearing, not
incidental:

1. **Any component carrying an `attachment` is rebuilt as `CylinderGeometry(endRadius, baseRadius, length)`
   and repositioned to `endpoint.start`** (`generate_threejs_factory.py:3119-3122`). The declared primitive
   is discarded. That turns an octagonal knuckle plate into a tube, every overlay panel into a tube, and the
   two cuff bands into a cone hanging below the wrist.
2. **`--strict-quality` requires that attachment record** on every child component, so the overlay cannot
   simply drop it.

Use the forge pipeline for its **intake, evidence and gates**; use the spec-driven builder for the
geometry.

---

## Step 1 — Split the listing image before anything else

A marketplace listing is one image with several views, a caption band and a tiled watermark.

```bash
python3 forge/stage1_intake/split_composite_plate.py \
    --image listing.png --out-dir plates --roles dorsal palmar \
    --provenance split-provenance.json
```

Necessary, not convenience: the same path submitted twice yields the same pHash, sets `duplicateOfHash`,
and `_paired_glove_plate_override` refuses it (`cs2_manifest.py:118-132`).

**It cannot remove a watermark that crosses the item.** Do not project such a plate onto geometry — the
watermark bakes into the texture.

## Step 2 — Observe before measuring

Work `grimoire/intake/image_analysis.md` layer by layer, **on crops at 2x**. The things that decide the
model are only visible zoomed: rolled hems with visible bores vs caps, pointed cones vs domes, how many
spike populations, how many cuff bands. Write it to a file; every later number traces back to it.

## Step 3 — Measure colour from pixels, never from memory

Hue-bucket histogram over the whole plate (12 buckets of 30°), plus **median value, median saturation,
p90 value, p90 saturation**. For Hydra CH: 210° blue 43.9%, 30° gold 31.3%, medV 0.376, medS 0.194,
p90V 0.620, p90S 0.391. The pair (medV, medS) says the surface is a mid-dark desaturated field carrying
saturated blotches — authoring it as a bright tint produces pale lavender. p90V says how bright the
highlights must get; p90S catches over-saturated blotches the median hides.

Then extract real PBR per material from its own crop
(`forge/stage1_intake/extract_pbr_evidence.py`, confidence below 0.7 is a stop signal).

## Step 4 — The organic shell is ONE signed distance field

This is the correction that ended the "box with tubes pushed into its edge" era. A hand is continuous:
digits grow out of knuckles through webbing, the thumb grows out of the thenar mass, and no seam exists
at any of those joins. Every mesh-composition attempt — extruded outlines, lofted sections, tubes
positioned against a slab — left a hard intersection line at every junction, and that line is what makes
a model read as parts instead of a glove.

`shell-sdf.mjs` builds: a rounded box whose half-width/half-depth vary along Y from **measured
cross-sections** (wrist narrow-deep → heel deepest → mid-palm widest → knuckle line thinnest, arched),
tapered capsules per digit and thumb `smin`-blended in, and tapered bores subtracted so the openings are
real holes. Meshed with naive surface nets at resolution ~200.

Traps, each found the expensive way:

| trap | symptom | rule |
|---|---|---|
| bore parameterised on its own overshooting segment | wall top at 74% of nominal tip; hem rings float | parameterise bore radius on the **digit's own axis**, clip the solid region with a half-space along the axis |
| palm solid stops at the last section while `topY()` reports the arch | digits start above solid material; `smin` bridges the gap as a blob | the solid's top edge must carry the same arch the placement query reports |
| blend radius at default | four stalls fuse into one mound | `blend` ≈ 0.05 palm-widths; melting is a spec bug, not a style |
| no `uv` attribute on generated geometry | grain and blotch maps sample (0,0); shell renders flat plastic | every generated geometry gets uvs; cylindrical about Y works for a hand |
| hem rings placed from spec numbers | rings float a cap-radius above the stall | place hems from the **same axis endpoints the field used** |
| palm reaching the knuckle arch everywhere | stalls read as notches in a wall | end the body at the knuckle band; let the tubes stand free above it |

Hard parts stay meshes: octagon-extruded plate, tapered-tube emblem serpents (`taperedTube`, thick coil
→ thin neck), cone spikes (instanced), open-tube cuff bands, extruded strap with pivot. Rounded
protrusions below grid resolution (hem tori) stay meshes too.

## Step 5 — Probe the field numerically BEFORE rendering

```bash
node runtime/glove-procedural/probe-shell.mjs <spec.mjs>
```

It walks each digit axis and fails if the wall stops short of the nominal tip (beyond the expected
capsule-dome allowance) or the bore never opens. This caught the bore eating a quarter of every digit —
a defect the dorsal render **could not show**, because the hem ring drawn at the nominal tip hid it.
A render cannot review geometry that something else is drawn on top of; a probe can.

## Step 6 — Iterate against measurements, not impressions

Each round: capture → comparison sheet → **measure** (silhouette aspect, width profile at 7 heights,
hue histogram, medV/medS/p90V/p90S) → change the one thing the numbers name → recapture. Eyeballing
alternately over- and under-corrects; the width profile says *where* the silhouette is wrong ("body
reaches 0.58 of box width a fifth of the way down where the reference reaches 0.77" → stalls too long,
not palm too narrow).

Judge form on a map-stripped render, and judge it from 36 angles
(`HYDRA_TURNTABLE=1 … "?static=1&stripped=1"`). One dorsal view is not evidence.

## Step 7 — Get an independent critique, and give it the turntable

Build two 6x6 contact sheets (textured, map-stripped) and send them with the reference via NotebookLM.
Ask for: features absent, features wrong in proportion **with magnitudes**, defects visible only from
some angles, whether the surface reads as material or as a tiled photograph, ranked fixes, one score,
and no praise. The first review of this build returned 0.15/1.0 and named the cause of every defect,
including two a self-review had missed.

## The order that matters

1. split → 2. observe at 2x → 3. measure colour and PBR → 4. **SDF shell first, map-stripped** →
5. probe the field → 6. iterate against measurements → 7. external critique → repeat 4–7.

Materials before form is the trap. A projected photograph makes a slab look like a glove from the one
angle the photograph was taken at, and every pixel-aligned gate will agree with it.
