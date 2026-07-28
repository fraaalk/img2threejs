# Spec: Driver Gloves - Glove Item Specification

## Item Overview
- **Family:** Glove
- **Subtype:** Driver Gloves
- **Style:** Classic driving, luxury leather
- **Notable Skins:** King Snake, Imperial Plaid, Overtake

## Geometry Breakdown

### Components
| Component | Primitive | Dimensions | Notes |
|-----------|-----------|------------|-------|
| Palm | Curved Plane | 180x100mm | Soft high-grade leather |
| Fingers (5) | Cylinders | 60-80mm length, 15-18mm radius | Full-fingered, separate articulation |
| Backhand | Plane | 180x90mm | Classic driving style with knuckle cutouts |
| Knuckle Holes | Circles | 15mm diameter | Perforated leather |
| Wrist Cuff | Cylinder | 80mm diameter | Slip-on or buckle strap |
| Perforations | Holes | 3mm diameter | Grip/ventilation |

### Vertex Budget
- Total: ~6,800 vertices
- Palm: ~1,200
- Fingers: ~2,500 (500 each)
- Backhand: ~1,100
- Knuckle Holes: ~400
- Wrist: ~500
- Perforations: ~1,100

## Material Assignments

| Material | Components | Properties |
|----------|------------|------------|
| Suede Leather | Palm, Finger tips | Roughness: 0.7, Metallic: 0.0 |
| Smooth Leather | Backhand | Roughness: 0.4, Metallic: 0.0 |
| Metal | Buckle (if applicable) | Roughness: 0.2, Metallic: 0.9 |

## Wear Zones

| Zone | Location | Wear Type | Intensity Range |
|------|----------|-----------|-----------------|
| Palm Surface | Contact area | Smooth wear | 0.1-0.4 |
| Finger Tips | Tactile zones | Fraying | 0.1-0.3 |
| Knuckle Holes | Cutout edges | Fraying | 0.2-0.5 |
| Wrist Edge | Cuff area | Smooth wear | 0.1-0.3 |

## UV Mapping Strategy
- Atlas: Glove family atlas
- Projection: palmar view for palm regions, dorsal view for backhand regions
- Scale: 1:1 for palm, 0.9:1 for fingers

## Animation Sockets
- **wrist_pivot:** Wrist rotation point
- **finger_joints (5x):** Knuckle articulation
- **thumb_pivot:** Thumb opposition
- **buckle_clasp:** Buckle closure (if applicable)

## Reference Images Required
- Palmar view with registered crop and hand identity
- Dorsal view with registered crop and hand identity
- Side view (for finger profile)
