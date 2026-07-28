# Spec: Broken Fang Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Broken Fang Gloves
- **Style:** Tactical with unique fang pattern
- **Notable Skins:** Jade, Yellow-banded, Stone Cold

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Curved Plane | 180x100mm | Synthetic leather with grip zones |
| Fingers (5) | Cylinders | 60-80mm length, 16-18mm radius | Separate fingers with fang accents |
| Backhand | Textured Plane | 180x90mm | Broken Fang pattern overlay |
| Fang Accents | Triangular Prisms | Various | Distinctive fang design elements |
| Wrist Band | Ribbon | 200x30mm | Velcro closure |
| Grip Zones | Offset Planes | Palm areas | Enhanced grip texture |

### Vertex Budget
- Total: ~7,000 vertices
- Palm: ~1,300
- Fingers: ~2,500 (500 each)
- Backhand: ~1,100
- Fang Accents: ~600
- Wrist: ~500
- Grip Zones: ~500
- Controls: ~500

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Synthetic Leather | Palm | Roughness: 0.6, Metallic: 0.0 |
| Textured Fabric | Backhand | Roughness: 0.7, Metallic: 0.0 |
| Rubberized | Grip zones | Roughness: 0.4, Metallic: 0.1 |
| Metallic | Fang accents | Roughness: 0.3, Metallic: 0.7 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.4 |
| Fang Accents | Decorative elements | Scratches | 0.1-0.3 |
| Finger Tips | Tactile zones | Fraying | 0.1-0.3 |
| Wrist Edge | Closure area | Fraying | 0.2-0.5 |

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
- Side view (for fang accent detail)
