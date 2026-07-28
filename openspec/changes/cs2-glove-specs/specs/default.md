# Spec: Default Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Default Gloves
- **Style:** Basic tactical
- **Notable Skins:** None (base model)

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Curved Plane | 180x100mm | Basic synthetic material |
| Fingers (5) | Cylinders | 60-80mm length, 16-18mm radius | Standard finger design |
| Backhand | Plane | 180x90mm | Basic fabric |
| Wrist Band | Ribbon | 200x25mm | Simple Velcro |
| Stitching | Lines | Various | Visible seam lines |

### Vertex Budget
- Total: ~5,800 vertices
- Palm: ~1,100
- Fingers: ~2,200 (440 each)
- Backhand: ~900
- Wrist: ~400
- Stitching: ~1,200

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Basic Synthetic | Palm, Fingers | Roughness: 0.7, Metallic: 0.0 |
| Basic Fabric | Backhand | Roughness: 0.8, Metallic: 0.0 |
| Elastic | Wrist band | Roughness: 0.7, Metallic: 0.0 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.3 |
| Finger Tips | Tactile zones | Fraying | 0.1-0.2 |
| Wrist Edge | Closure area | Fraying | 0.1-0.3 |
| Stitching | Seam lines | Fraying | 0.1-0.2 |

## UV Mapping Strategy
- Atlas: Glove family atlas
- Projection: palmar view for palm regions, dorsal view for backhand regions
- Scale: 1:1 (simple geometry)

## Animation Sockets
- **wrist_pivot:** Wrist rotation point
- **finger_joints (5x):** Knuckle articulation
- **thumb_pivot:** Thumb opposition

## Reference Images Required
- Palmar view with registered crop and hand identity
- Dorsal view with registered crop and hand identity
