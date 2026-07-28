# Spec: Moto Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Moto Gloves
- **Style:** Armored, motorcycle-style
- **Notable Skins:** Transport, Boom!, Eclipse

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Thick Padded Plane | 180x100mm | Heavy-duty synthetic suede |
| Fingers (5) | Pre-curved Cylinders | 60-80mm length, 18-20mm radius | Extra padding on joints |
| Backhand | Rigid Shell | 180x90mm | Hard knuckle guards (TPR/carbon) |
| Knuckle Guards | Convex Hulls | 40x30x15mm | Hard armor plates |
| Wrist Cuff | Wide Cylinder | 90mm diameter | Heavy-duty Velcro strap |
| Joint Pads | Rings | 8mm height | Extra padding on finger joints |

### Vertex Budget
- Total: ~7,500 vertices
- Palm: ~1,500
- Fingers: ~2,800 (560 each)
- Backhand: ~1,200
- Knuckle Guards: ~600
- Wrist: ~600
- Joint Pads: ~800

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Synthetic Suede | Palm | Roughness: 0.7, Metallic: 0.0 |
| Hard Plastic | Knuckle Guards | Roughness: 0.3, Metallic: 0.2 |
| Thick Synthetic | Fingers, Backhand | Roughness: 0.6, Metallic: 0.0 |
| Velcro | Wrist strap | Roughness: 0.8, Metallic: 0.0 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.4 |
| Knuckle Guards | Hard plates | Scratches | 0.1-0.3 |
| Finger Joints | Padding areas | Fraying | 0.1-0.3 |
| Wrist Edge | Cuff area | Fraying | 0.2-0.5 |

## UV Mapping Strategy
- Atlas: Glove family atlas
- Projection: palmar view for palm regions, dorsal view for backhand regions
- Scale: 1:1 for palm, 0.85:1 for fingers (bulkier)

## Animation Sockets
- **wrist_pivot:** Wrist rotation point
- **finger_joints (5x):** Knuckle articulation
- **thumb_pivot:** Thumb opposition

## Reference Images Required
- Palmar view with registered crop and hand identity
- Dorsal view with registered crop and hand identity
- Side view (for knuckle guard profile)
