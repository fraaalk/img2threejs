# Spec: Specialist Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Specialist Gloves
- **Style:** Tactical, reinforced
- **Notable Skins:** Fade, Crimson Web, Kimono

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Layered Planes | 180x100mm | Black leather + reinforcement inserts |
| Fingers (5) | Cylinders | 60-80mm length, 15-18mm radius | Separate fingers, index thinner |
| Backhand | Textured Plane | 180x90mm | Dark blue/black with gradient inserts |
| Reinforcement Inserts | Planes | Various | Dark gray abrasion resistance |
| Wrist Band | Ribbon | 200x35mm | Industrial-strength Velcro |
| Thumb Saddle | Box | 30x20x10mm | Reinforced for stability |

### Vertex Budget
- Total: ~7,000 vertices
- Palm: ~1,400
- Fingers: ~2,500 (500 each)
- Backhand: ~1,100
- Inserts: ~500
- Wrist: ~500
- Thumb: ~400
- Controls: ~600

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Black Leather | Palm, Fingers | Roughness: 0.5, Metallic: 0.0 |
| Reinforcement | Inserts | Roughness: 0.6, Metallic: 0.0 |
| Textured Fabric | Backhand | Roughness: 0.7, Metallic: 0.0 |
| Rubberized | Gradient inserts | Roughness: 0.4, Metallic: 0.1 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.4 |
| Finger Tips | Tactile zones | Fraying | 0.1-0.3 |
| Reinforcement | Insert edges | Scratches | 0.1-0.3 |
| Wrist Band | Velcro area | Fraying | 0.2-0.5 |

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
- Side view (for finger profile)
