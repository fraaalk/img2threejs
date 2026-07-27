import * as THREE from 'three';

export type GeneratedKnifeSpec = Readonly<{
  materialChannels: readonly string[];
  environmentAvailable: boolean;
}>;

export type GeneratedFamilySpec = Readonly<{
  family: 'pistol' | 'rifle';
  materialChannels: readonly string[];
}>;

export function createGeneratedKnife(spec: GeneratedKnifeSpec): THREE.Group {
  const root = new THREE.Group();
  root.name = 'generated-reference-projected-knife';
  const substrate = new THREE.MeshStandardMaterial({ color: '#272a31', metalness: 0.95, roughness: 0.18 });
  substrate.userData.materialChannels = spec.materialChannels;
  const bladeShape = new THREE.Shape();
  bladeShape.moveTo(-0.08, -0.04); bladeShape.lineTo(0.08, -0.04); bladeShape.lineTo(0.82, 0.0);
  bladeShape.lineTo(1.35, 0.17); bladeShape.lineTo(1.55, 0.0); bladeShape.lineTo(1.35, -0.17);
  bladeShape.lineTo(0.82, -0.11); bladeShape.lineTo(0.08, 0.04); bladeShape.lineTo(-0.08, 0.04); bladeShape.closePath();
  const blade = new THREE.Mesh(new THREE.ExtrudeGeometry(bladeShape, { depth: 0.06, bevelEnabled: true, bevelSize: 0.018, bevelThickness: 0.015 }), substrate);
  blade.name = 'blade'; blade.rotation.x = Math.PI / 2; blade.position.set(-0.86, 0.04, -0.03); blade.castShadow = true; root.add(blade);
  const grip = new THREE.Mesh(new THREE.CapsuleGeometry(0.15, 0.62, 12, 24), substrate);
  grip.name = 'handle'; grip.rotation.z = Math.PI / 2; grip.position.set(-1.17, -0.22, 0); grip.scale.set(1, 1, 0.8); grip.castShadow = true; root.add(grip);
  const guard = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.035, 12, 32, Math.PI), substrate);
  guard.name = 'guard'; guard.rotation.z = Math.PI / 2; guard.position.set(-0.75, -0.04, 0); root.add(guard);
  root.rotation.z = -0.12; root.position.y = 0.05;
  root.userData.materialChannels = spec.materialChannels;
  root.userData.environmentAvailable = spec.environmentAvailable;
  return root;
}

export function createGeneratedKnifeEnvironment(): THREE.Group {
  const lights = new THREE.Group();
  const hemi = new THREE.HemisphereLight('#dbe7ff', '#17191d', 2.2); lights.add(hemi);
  const key = new THREE.DirectionalLight('#ffffff', 4); key.position.set(2, 2, 4); key.castShadow = true; lights.add(key);
  const rim = new THREE.DirectionalLight('#5478ff', 3); rim.position.set(-3, 0, -2); lights.add(rim);
  lights.userData.environment = 'runtime-neutral-environment';
  return lights;
}

export function createGeneratedFamily(spec: GeneratedFamilySpec): THREE.Group {
  const root = new THREE.Group();
  root.name = `generated-reference-projected-${spec.family}`;
  const material = new THREE.MeshStandardMaterial({ color: '#272a31', metalness: 0.92, roughness: 0.22 });
  material.userData.materialChannels = spec.materialChannels;
  if (spec.family === 'pistol') {
    const slide = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.42, 0.34), material);
    slide.name = 'slide'; slide.position.y = 0.28; root.add(slide);
    const frame = new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.55, 0.42), material);
    frame.name = 'frame'; frame.position.y = -0.18; root.add(frame);
    const magazine = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.85, 0.28), material);
    magazine.name = 'magazine'; magazine.position.set(-0.25, -0.75, 0); root.add(magazine);
    const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.7, 24), material);
    barrel.name = 'barrel'; barrel.rotation.z = Math.PI / 2; barrel.position.x = 1.12; root.add(barrel);
  } else {
    const receiver = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.62, 0.55), material);
    receiver.name = 'receiver'; root.add(receiver);
    const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 2.8, 24), material);
    barrel.name = 'barrel'; barrel.rotation.z = Math.PI / 2; barrel.position.x = 2.15; root.add(barrel);
    const scope = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 1.2, 24), material);
    scope.name = 'scope'; scope.rotation.z = Math.PI / 2; scope.position.set(0.15, 0.55, 0); root.add(scope);
    const stock = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.72, 0.52), material);
    stock.name = 'stock'; stock.position.x = -1.45; root.add(stock);
  }
  root.userData.materialChannels = spec.materialChannels;
  return root;
}
