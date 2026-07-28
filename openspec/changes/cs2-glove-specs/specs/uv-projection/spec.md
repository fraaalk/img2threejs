## MODIFIED Requirements

### Requirement: UV projection system
Agents SHALL map reference images to existing mesh UVs using scale/offset/rotation matrices. For `glove-multiview-v1`, each assignment SHALL use an anatomical `dorsal|palmar` role, named region mask, material slot, and immutable UV island; it MUST NOT use generic `front|back` angles or project across the opposite anatomical role. Non-glove families may retain legacy generic angle names.

#### Scenario: Apply a palmar glove reference to mesh
- **WHEN** the agent bakes a palmar glove reference
- **THEN** it maps only to named palmar-region masks and cannot overwrite dorsal, unsupported gusset, or sidewall UV islands

### Requirement: UV projection parameters
The schema SHALL support scale (vec2), offset (vec2), rotation (float in radians). Glove assignments SHALL additionally preserve source view ID, region ID, mask, material slot, overlap priority, and per-channel color-space semantics.

#### Scenario: Glove UV projection configuration
- **WHEN** the agent configures an observed dorsal shell
- **THEN** output contains its `dorsal` source view, named UV island/mask, and sRGB base-color mapping without mutable runtime UV generation
