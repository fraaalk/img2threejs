import * as THREE from 'three';

export type GeneratedGloveSpec = Readonly<{
  materialChannels: readonly string[];
  environmentAvailable: boolean;
}>;

type GloveMaterials = Readonly<{
  green: THREE.MeshStandardMaterial;
  black: THREE.MeshStandardMaterial;
  gray: THREE.MeshStandardMaterial;
  trim: THREE.MeshStandardMaterial;
  wear: THREE.MeshStandardMaterial;
  seam: THREE.LineBasicMaterial;
}>;

function roundedShape(width: number, height: number, radius: number): THREE.Shape {
  const shape = new THREE.Shape();
  shape.moveTo(-width / 2 + radius, -height / 2);
  shape.lineTo(width / 2 - radius, -height / 2);
  shape.quadraticCurveTo(width / 2, -height / 2, width / 2, -height / 2 + radius);
  shape.lineTo(width / 2, height / 2 - radius);
  shape.quadraticCurveTo(width / 2, height / 2, width / 2 - radius, height / 2);
  shape.lineTo(-width / 2 + radius, height / 2);
  shape.quadraticCurveTo(-width / 2, height / 2, -width / 2, height / 2 - radius);
  shape.lineTo(-width / 2, -height / 2 + radius);
  shape.quadraticCurveTo(-width / 2, -height / 2, -width / 2 + radius, -height / 2);
  return shape;
}

function roundedPlate(width: number, height: number, depth: number, material: THREE.Material): THREE.Mesh {
  const geometry = new THREE.ExtrudeGeometry(roundedShape(width, height, Math.min(width, height) * 0.16), {
    bevelEnabled: true,
    bevelSegments: 2,
    bevelSize: 0.035,
    bevelThickness: 0.035,
    depth,
    curveSegments: 8,
  });
  geometry.center();
  return new THREE.Mesh(geometry, material);
}

function makeMaterials(spec: GeneratedGloveSpec): GloveMaterials {
  const green = new THREE.MeshStandardMaterial({ color: '#68b936', roughness: 0.68, metalness: 0.02 });
  const black = new THREE.MeshStandardMaterial({ color: '#141a19', roughness: 0.82, metalness: 0.03 });
  const gray = new THREE.MeshStandardMaterial({ color: '#7f8b8a', roughness: 0.9, metalness: 0.01 });
  const trim = new THREE.MeshStandardMaterial({ color: '#26342c', roughness: 0.74, metalness: 0.02 });
  const wear = new THREE.MeshStandardMaterial({ color: '#a0a28c', roughness: 0.96, metalness: 0 });
  const seam = new THREE.LineBasicMaterial({ color: '#b8c4b3', transparent: true, opacity: 0.42 });
  for (const material of [green, black, gray, trim, wear]) {
    material.userData.materialChannels = spec.materialChannels;
  }
  return { green, black, gray, trim, wear, seam };
}

function addSeam(group: THREE.Group, materials: GloveMaterials, width: number, height: number, z: number): void {
  const points = [
    new THREE.Vector3(-width / 2, -height / 2, z),
    new THREE.Vector3(width / 2, -height / 2, z),
    new THREE.Vector3(width / 2, height / 2, z),
    new THREE.Vector3(-width / 2, height / 2, z),
    new THREE.Vector3(-width / 2, -height / 2, z),
  ];
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  group.add(new THREE.Line(geometry, materials.seam));
}

function addWearPatch(group: THREE.Group, materials: GloveMaterials, x: number, y: number, z: number, sx: number, sy: number): void {
  const patch = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 6), materials.wear);
  patch.position.set(x, y, z);
  patch.scale.set(sx, sy, 0.16);
  group.add(patch);
}

function addWristFrame(group: THREE.Group, materials: GloveMaterials): void {
  const left = new THREE.Mesh(new THREE.BoxGeometry(0.055, 0.28, 0.08), materials.green);
  left.position.set(-0.38, -0.83, 0.18);
  const right = left.clone();
  right.position.x = 0.38;
  const bottom = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.055, 0.08), materials.green);
  bottom.position.set(0, -0.97, 0.18);
  group.add(left, right, bottom);
}

function makeGlove(sign: -1 | 1, dorsal: boolean, materials: GloveMaterials): THREE.Group {
  const glove = new THREE.Group();
  glove.name = dorsal ? `sport-glove-${sign < 0 ? 'left' : 'right'}-dorsal` : `sport-glove-${sign < 0 ? 'left' : 'right'}-palm`;
  const palm = roundedPlate(0.86, 1.28, 0.3, dorsal ? materials.black : materials.gray);
  palm.position.y = -0.02;
  glove.add(palm);

  const fingerX = [-0.34, -0.115, 0.115, 0.34];
  const fingerLength = [0.72, 0.98, 1.12, 0.88];
  fingerX.forEach((x, index) => {
    const length = fingerLength[index] ?? 0.9;
    const finger = new THREE.Mesh(new THREE.CapsuleGeometry(0.105, length, 8, 16), dorsal ? materials.black : materials.green);
    finger.position.set(x, 0.72 + (length - 0.9) * 0.22, 0);
    finger.rotation.z = x * -0.16;
    finger.scale.z = 0.9;
    glove.add(finger);
    const tip = new THREE.Mesh(new THREE.CapsuleGeometry(0.11, 0.18, 6, 12), materials.green);
    tip.position.set(x, finger.position.y + length / 2 + 0.06, 0.025);
    tip.scale.z = 0.94;
    glove.add(tip);
    const gusset = new THREE.Mesh(new THREE.BoxGeometry(0.035, length * 0.64, 0.06), materials.trim);
    gusset.position.set(x - 0.1 * Math.sign(x || 1), finger.position.y, 0.12);
    gusset.rotation.z = x * -0.16;
    glove.add(gusset);
    if (!dorsal) addWearPatch(glove, materials, x, finger.position.y + length * 0.27, 0.18, 1.25, 0.5);
  });

  const thumb = new THREE.Mesh(new THREE.CapsuleGeometry(0.13, 0.48, 8, 16), materials.green);
  thumb.position.set(sign * 0.54, 0.02, 0);
  thumb.rotation.z = sign * -0.75;
  glove.add(thumb);
  const thumbGuard = roundedPlate(0.24, 0.48, 0.08, dorsal ? materials.green : materials.trim);
  thumbGuard.position.set(sign * 0.47, 0.12, 0.16);
  thumbGuard.rotation.z = sign * -0.55;
  glove.add(thumbGuard);

  if (dorsal) {
    const knuckleX = [-0.3, -0.1, 0.1, 0.3];
    knuckleX.forEach((x, index) => {
      const plate = roundedPlate(0.16, 0.3, 0.085, index % 2 === 0 ? materials.trim : materials.black);
      plate.position.set(x, 0.43, 0.19);
      plate.rotation.z = x * -0.12;
      glove.add(plate);
      const rib = new THREE.Mesh(new THREE.BoxGeometry(0.025, 0.22, 0.035), materials.gray);
      rib.position.set(x, 0.43, 0.25);
      rib.rotation.z = x * -0.12;
      glove.add(rib);
    });
    addWearPatch(glove, materials, -0.2, 0.02, 0.19, 1.7, 0.55);
    addWearPatch(glove, materials, 0.23, -0.34, 0.19, 1.3, 0.4);
  } else {
    const pad = roundedPlate(0.62, 0.68, 0.065, materials.gray);
    pad.position.set(0, -0.05, 0.18);
    glove.add(pad);
    const heel = roundedPlate(0.44, 0.32, 0.07, materials.gray);
    heel.position.set(-sign * 0.16, -0.43, 0.18);
    heel.rotation.z = sign * 0.18;
    glove.add(heel);
    addWearPatch(glove, materials, -0.29, -0.38, 0.23, 2.2, 0.46);
    addWearPatch(glove, materials, 0.27, -0.16, 0.23, 1.6, 0.4);
  }

  const cuff = roundedPlate(0.92, 0.26, 0.28, materials.gray);
  cuff.position.y = -0.82;
  glove.add(cuff);
  addWristFrame(glove, materials);
  addSeam(glove, materials, 0.72, 0.56, 0.2);
  glove.position.x = sign * 0.72;
  glove.rotation.y = dorsal ? sign * -0.08 : Math.PI + sign * 0.08;
  glove.rotation.z = sign * 0.035;
  return glove;
}

export function createGeneratedGlovePair(spec: GeneratedGloveSpec): THREE.Group {
  const root = new THREE.Group();
  root.name = 'generated-reference-projected-sport-gloves';
  const materials = makeMaterials(spec);
  root.add(
    makeGlove(-1, true, materials),
    makeGlove(-1, false, materials),
    makeGlove(1, true, materials),
    makeGlove(1, false, materials),
  );
  root.position.y = -0.05;
  root.scale.setScalar(0.86);
  root.userData.materialChannels = spec.materialChannels;
  root.userData.environmentAvailable = spec.environmentAvailable;
  root.userData.referenceRoute = 'front-and-palm-paired-projection';
  return root;
}

export function createGeneratedGloveEnvironment(): THREE.Group {
  const lights = new THREE.Group();
  const hemi = new THREE.HemisphereLight('#e9f9e1', '#08100b', 2.4);
  const key = new THREE.DirectionalLight('#f2fff0', 4.2);
  key.position.set(2.5, 3.2, 4.5);
  key.castShadow = true;
  const rim = new THREE.DirectionalLight('#8edc52', 4.4);
  rim.position.set(-3.5, 1.2, -2.5);
  lights.add(hemi, key, rim);
  lights.userData.environment = 'emerald-inspection-bay-v1';
  return lights;
}
