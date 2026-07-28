# Spec: Sport Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Sport Gloves
- **Style:** Athletic, high-dexterity
- **Notable Skins:** Vice, Superconductor, Amphibious

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Curved Plane | 180x100mm | Synthetic/leather with padding |
| Fingers (5) | Cylinders | 60-80mm length, 15-18mm radius | Separate-finger design |
| Backhand | Mesh Plane | 180x90mm | Breathable polyester knit |
| Wrist Band | Ribbon | 200x25mm | Low-profile Velcro/elastic |
| Finger Joints | Rings | 5mm height | Padding offsets |
| Gussets | Triangles | Between fingers | V-shaped sections |

### Vertex Budget
- Total: ~6,500 vertices
- Palm: ~1,200
- Fingers: ~2,500 (500 each)
- Backhand: ~1,000
- Wrist: ~400
- Joints: ~800
- Gussets: ~600

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Synthetic Leather | Palm, Finger tips | Roughness: 0.6, Metallic: 0.0 |
| Polyester Mesh | Backhand | Roughness: 0.8, Metallic: 0.0 |
| Elastic | Wrist band | Roughness: 0.7, Metallic: 0.0 |
| Vibrant Synthetic | Color patterns | Roughness: 0.5, Metallic: 0.1 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.4 |
| Finger Tips | Tactile zones | Fraying | 0.1-0.3 |
| Backhand | Mesh surface | Pilling | 0.1-0.3 |
| Wrist Edge | Closure area | Fraying | 0.2-0.5 |

## UV Mapping Strategy
- Atlas: Glove family atlas (shared with other gloves)
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
