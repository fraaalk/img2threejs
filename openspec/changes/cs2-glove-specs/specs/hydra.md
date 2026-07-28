# Spec: Hydra Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Hydra Gloves
- **Style:** Tactical hard-knuckle
- **Notable Skins:** Case Hardened, Emerald, Rattler

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Colored Patch Plane | 180x100mm | Large sky-blue/patterned patch |
| Fingers (5) | Cylinders | 60-80mm length, 16-18mm radius | Fully separate, padded joints |
| Backhand | Rigid Shell | 180x90mm | Tactical hard-knuckle guard |
| Joint Pad Rings | Rings | 5mm height | Padded reinforcements |
| Wrist Band | Integrated Cuff | 80mm diameter | Sturdy Velcro closure |
| Metallic Accents | Planes | Various | Case Hardened patterns |

### Vertex Budget
- Total: ~7,200 vertices
- Palm: ~1,400
- Fingers: ~2,600 (520 each)
- Backhand: ~1,200
- Joint Pads: ~700
- Wrist: ~500
- Accents: ~800

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Suede Leather | Palm | Roughness: 0.6, Metallic: 0.0 |
| Four-way Stretch | Backhand | Roughness: 0.5, Metallic: 0.0 |
| Hard Plastic | Knuckle Guard | Roughness: 0.3, Metallic: 0.2 |
| Metallic | Case Hardened accents | Roughness: 0.2, Metallic: 0.8 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.4 |
| Knuckle Guard | Hard plate | Scratches | 0.1-0.3 |
| Joint Pads | Padding areas | Fraying | 0.1-0.3 |
| Wrist Edge | Cuff area | Fraying | 0.2-0.5 |

## UV Mapping Strategy
- Atlas: Glove family atlas
- Projection: palmar view for palm regions, dorsal view for backhand regions
- Scale: 1:1 for palm, 0.9:1 for fingers

## Animation Sockets
- **wrist_pivot:** Wrist rotation point
- **finger_joints (5x):** Knuckle articulation
- **thumb_pivot:** Thumb opposition

## Reference Images Required
- Palmar view with registered crop and hand identity
- Dorsal view with registered crop and hand identity
- Side view (for knuckle guard profile)
