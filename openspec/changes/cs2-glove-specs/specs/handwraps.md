# Spec: Hand Wraps - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Hand Wraps
- **Style:** Minimalist cloth wraps
- **Notable Skins:** Overprint, Arid, Slaughter

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm Wraps | Ribbon Strips | 180x100mm | Layered cloth/tape |
| Finger Wraps | Ribbon Strips | 60-80mm length | Partial coverage, tips exposed |
| Backhand Wraps | Ribbon Strips | 180x90mm | Cloth wrap across metacarpals |
| Wrist Wraps | Extended Ribbons | 200x30mm | Wrap-and-tuck or elastic |
| Exposed Areas | Open Zones | Fingertips, knuckles | Visible skin |

### Vertex Budget
- Total: ~5,500 vertices
- Palm Wraps: ~1,200
- Finger Wraps: ~1,800 (360 each)
- Backhand Wraps: ~1,000
- Wrist Wraps: ~800
- Exposed Areas: ~700

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Rough Cloth | All wraps | Roughness: 0.9, Metallic: 0.0 |
| Elastic | Wrist extension | Roughness: 0.8, Metallic: 0.0 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Fraying | 0.1-0.4 |
| Wrap Edges | All edges | Fraying | 0.2-0.5 |
| Wrist Area | Closure zone | Fraying | 0.1-0.3 |
| Exposed Skin | Fingertips/knuckles | scratches (on skin) | 0.1-0.2 |

## UV Mapping Strategy
- Atlas: Glove family atlas
- Projection: palmar view for palm regions, dorsal view for backhand regions
- Scale: 1:1 (wraps conform to hand shape)

## Animation Sockets
- **wrist_pivot:** Wrist rotation point
- **finger_joints (5x):** Knuckle articulation (limited by wraps)
- **thumb_pivot:** Thumb opposition

## Reference Images Required
- Palmar view with registered crop and hand identity
- Dorsal view with registered crop and hand identity
- Side view (for wrap layering)
