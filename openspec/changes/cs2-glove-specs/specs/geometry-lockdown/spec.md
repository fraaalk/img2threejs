## MODIFIED Requirements

### Requirement: GLTF asset contract
The pipeline SHALL load pre-baked GLTF/GLB files as the geometry source. Geometry is IMMUTABLE after loading. A locked-down `glove-multiview-v1` pair SHALL contain separately baked canonical-left and derived-right positive-determinant renderable nodes, named anatomical dorsal/palmar/thumb/gusset/cuff regions, and immutable UV islands. Runtime negative scale, runtime reflection, and runtime UV computation are prohibited.

#### Scenario: Baked right glove is loaded
- **WHEN** the pipeline loads a locked-down right glove asset
- **THEN** its node determinant is positive, winding/normals/tangents are valid, and it exposes the same named anatomical regions as the canonical left asset
