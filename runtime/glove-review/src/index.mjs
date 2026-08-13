import { createHash } from 'node:crypto';
import { cp, lstat, readFile, writeFile } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

export const REQUIRED_CAPTURE_ROLES = Object.freeze([
  'dorsal', 'palmar', 'thumb-side-profile', 'left-three-quarter', 'right-three-quarter',
]);
export const ORBIT_CAPTURE_ROLES = Object.freeze(['orbit-a', 'orbit-b']);
export const MODEL_BUNDLE_VERSION = 'glove-model-bundle.v2';

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function digest(value) {
  return createHash('sha256').update(canonical(value)).digest('hex');
}

async function fileDigest(path) {
  const data = await readFile(path);
  return createHash('sha256').update(data).digest('hex');
}

async function relativeDescendant(root, value, label) {
  if (typeof value !== 'string' || value.length === 0 || isAbsolute(value)) throw new Error(`${label} must be a non-empty relative path`);
  const parts = value.split(/[\\/]/);
  if (parts.some((part) => part === '' || part === '.' || part === '..')) throw new Error(`${label} contains traversal`);
  const candidate = resolve(root, value);
  const rel = relative(root, candidate);
  if (rel === '' || rel === '..' || rel.startsWith(`..${sep}`) || isAbsolute(rel)) throw new Error(`${label} escapes artifact root`);
  let current = root;
  for (const part of parts) {
    current = resolve(current, part);
    if ((await lstat(current)).isSymbolicLink()) throw new Error(`${label} traverses a symlink`);
  }
  return candidate;
}

function validateCanonicalMesh(payload, id) {
  if (!payload || !Array.isArray(payload.vertices) || !Array.isArray(payload.indices) || !Array.isArray(payload.normals)) throw new Error(`canonical mesh payload missing fields: ${id}`);
  if (payload.vertices.length === 0 || payload.normals.length !== payload.vertices.length) throw new Error(`canonical mesh payload has incomplete vertices/normals: ${id}`);
  for (const vertex of payload.vertices) if (!Array.isArray(vertex) || vertex.length < 3 || vertex.slice(0, 3).some((value) => !Number.isFinite(value))) throw new Error(`canonical mesh payload has invalid vertex: ${id}`);
  for (const triangle of payload.indices) if (!Array.isArray(triangle) || triangle.length !== 3 || triangle.some((index) => !Number.isInteger(index) || index < 0 || index >= payload.vertices.length)) throw new Error(`canonical mesh payload has invalid triangle: ${id}`);
}

export async function loadAndVerifyBundle(bundlePath) {
  const absoluteBundlePath = resolve(bundlePath);
  const bundle = JSON.parse(await readFile(absoluteBundlePath, 'utf8'));
  if (bundle.version !== MODEL_BUNDLE_VERSION) throw new Error('v1 glove artifacts are diagnostic-only; a v2 model bundle is required');
  const unsigned = { ...bundle };
  delete unsigned.rootDigest;
  if (digest(unsigned) !== bundle.rootDigest) throw new Error('glove model bundle root digest mismatch');
  const base = dirname(absoluteBundlePath);
  const factoryPath = await relativeDescendant(base, bundle.factoryModule?.path, 'factoryModule.path');
  if (await fileDigest(factoryPath) !== bundle.factoryModule.sha256) throw new Error('factory hash mismatch');
  if (!Array.isArray(bundle.payloads) || bundle.payloads.length === 0) throw new Error('model bundle payloads are required');
  const payloads = [];
  for (const payload of bundle.payloads) {
    const payloadPath = await relativeDescendant(base, payload?.path, `payload:${payload?.id ?? 'unknown'}`);
    if (await fileDigest(payloadPath) !== payload.sha256) throw new Error(`payload hash mismatch: ${payload.id}`);
    const parsed = JSON.parse(await readFile(payloadPath, 'utf8'));
    validateCanonicalMesh(parsed, payload.id);
    payloads.push(parsed);
  }
  return { bundle, base, factoryPath, payloads };
}

export async function loadAndInstantiateBundle(bundlePath) {
  const verified = await loadAndVerifyBundle(bundlePath);
  const factory = await import(`${pathToFileURL(verified.factoryPath).href}?digest=${verified.bundle.rootDigest}`);
  if (factory.modelBundleVersion !== MODEL_BUNDLE_VERSION || typeof factory.createGloveModel !== 'function') throw new Error('factory does not implement the v2 glove model contract');
  const model = await factory.createGloveModel(verified.bundle, verified.payloads);
  if (!model || model.type !== 'Group' || !Array.isArray(model.meshes) || model.meshes.length !== verified.payloads.length) throw new Error('factory did not create every renderable glove mesh');
  for (const mesh of model.meshes) validateCanonicalMesh(mesh, mesh?.id ?? 'unknown');
  return { ...verified, model };
}

/**
 * This is intentionally a pending capture plan, not visual evidence. A browser adapter must
 * attach PNG paths, probes, and render-environment digest before it may mark it finalized.
 */
export async function createCaptureManifest(bundlePath, scene = {}) {
  const { bundle, model } = await loadAndInstantiateBundle(bundlePath);
  const captures = [...REQUIRED_CAPTURE_ROLES, ...ORBIT_CAPTURE_ROLES].map((role) => ({
    id: `capture-${role}`, role, camera: role, settledFrames: 2,
    modelBundleDigest: bundle.rootDigest, status: 'pending-render',
  }));
  const renderEnvironment = {
    viewport: scene.resolution ?? { width: 1024, height: 1024 },
    rendererVersion: scene.rendererVersion ?? 'browser-render-bridge-required-v2',
    devicePixelRatio: 1, settleFrames: 2,
  };
  const manifest = {
    version: 'capture-manifest.v2', modelBundleDigest: bundle.rootDigest,
    sceneVersion: scene.version ?? 'glove-review-scene-v2', renderEnvironment,
    renderEnvironmentDigest: digest(renderEnvironment), captures,
    finalized: false, modelMeshCount: model.meshes.length,
  };
  manifest.manifestDigest = digest(manifest);
  return manifest;
}

function viewerDocument(payloads, bundle) {
  const descriptor = bundle?.geometryDescriptor?.silhouetteInflation ?? null;
  // The armature route carries one implicit solid per hand, each already placed in its own bounds, so
  // the hand is not a parameter of one shared descriptor the way it is for the inflation.
  const armature = bundle?.geometryDescriptor?.armature ?? null;
  const atlas = bundle?.surfaceAtlas ?? null;
  const procedural = descriptor || armature;
  const encodedPayloads = JSON.stringify(procedural ? [] : payloads).replace(/</g, '\\u003c');
  const encodedDescriptor = JSON.stringify(descriptor).replace(/</g, '\\u003c');
  const encodedArmature = JSON.stringify(armature).replace(/</g, '\\u003c');
  const hands = JSON.stringify(descriptor?.hands ?? ['left', 'right']);
  return `<!doctype html><meta charset="utf-8"><title>Glove review runtime</title><style>html,body,canvas{margin:0;width:100%;height:100%;overflow:hidden}</style><canvas></canvas><script type="module">
import * as THREE from './three.module.js';
import { buildShellAttributes } from './shell.mjs';
import { buildSdfAtlasAttributes } from './sdf.mjs';
const payloads = ${encodedPayloads};
const descriptor = ${encodedDescriptor};
const armature = ${encodedArmature};
const canvas = document.querySelector('canvas');
const renderer = new THREE.WebGLRenderer({canvas, antialias:false, preserveDrawingBuffer:true});
renderer.setPixelRatio(1); renderer.setSize(1024,1024,false); renderer.setClearColor(0xffffff,1);
const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(35,1,0.01,100);
${atlas ? `// Unlit on purpose: the capture must be byte-identical across repeats, and a lit material
// makes the render depend on tone mapping and light state rather than on the glove.
const texture = await new THREE.TextureLoader().loadAsync('./${atlas.path}');
texture.colorSpace = THREE.SRGBColorSpace; texture.flipY = false;
const material = new THREE.MeshBasicMaterial({map: texture});` : `const material = new THREE.MeshNormalMaterial();`}
if (armature) {
  // Procedural: the browser polygonizes each hand's signed-distance field from the parameters the
  // review measured. The atlas uvs are unindexed per triangle, so this geometry carries no index.
  for (const hand of Object.keys(armature)) {
    const built = buildSdfAtlasAttributes(THREE, armature[hand].sdf);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(built.positions,3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(built.normals,3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(built.uvs,2));
    geometry.computeBoundingSphere();
    scene.add(new THREE.Mesh(geometry, material));
  }
} else if (descriptor) {
  // Procedural: the browser rebuilds the shell from the parameters the review measured, rather
  // than loading triangles somebody else baked.
  for (const hand of ${hands}) {
    const built = buildShellAttributes({...descriptor, hand});
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(built.positions,3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(built.uvs,2));
    geometry.setIndex(built.indices); geometry.computeVertexNormals(); geometry.computeBoundingSphere();
    scene.add(new THREE.Mesh(geometry, material));
  }
} else {
  for (const payload of payloads) { const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position', new THREE.Float32BufferAttribute(payload.vertices.flat(),3)); geometry.setAttribute('normal', new THREE.Float32BufferAttribute(payload.normals.flat(),3)); geometry.setIndex(payload.indices.flat()); geometry.computeBoundingSphere(); scene.add(new THREE.Mesh(geometry, material)); }
}
const setCamera = async (spec={}) => { const angle=(Number(spec.azimuthDegrees)||0)*Math.PI/180; const elevation=(Number(spec.elevationDegrees)||8)*Math.PI/180; const radius=3.8; camera.position.set(Math.sin(angle)*radius,Math.sin(elevation)*radius,Math.cos(angle)*radius); camera.lookAt(0,0,0); renderer.render(scene,camera); };
const countNonBackgroundPixels = () => { const gl=renderer.getContext(); const pixels=new Uint8Array(canvas.width*canvas.height*4); gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,pixels); let count=0; for(let i=0;i<pixels.length;i+=4) if(pixels[i]<248||pixels[i+1]<248||pixels[i+2]<248) count+=1; return count; };
const renderEnvironment = () => ({viewport:[canvas.width,canvas.height],devicePixelRatio:renderer.getPixelRatio(),settleFrames:2,renderer:renderer.constructor.name,threeRevision:THREE.REVISION,antialias:false,preserveDrawingBuffer:true,clearColor:'#ffffff',toneMapping:renderer.toneMapping});
await setCamera({}); window.__IMG2THREEJS_CAPTURE__={setCamera,countNonBackgroundPixels,renderEnvironment}; window.__IMG2THREEJS_READY__=true;
</script>`;
}

/** Write a self-contained browser route from verified bundle payloads. */
export async function writeBrowserRuntime(bundlePath, outputPath) {
  const { payloads, bundle, base } = await loadAndInstantiateBundle(bundlePath);
  const output = resolve(outputPath);
  const root = dirname(output);
  const threeBuild = resolve(new URL('../node_modules/three/build', import.meta.url).pathname);
  await cp(threeBuild, root, { recursive: true, force: true });
  for (const module of ['shell.mjs', 'sdf.mjs']) {
    await cp(resolve(new URL(`./${module}`, import.meta.url).pathname), resolve(root, module), { force: true });
  }
  if (bundle?.surfaceAtlas?.path) {
    // The atlas is hash-bound in the bundle, so a swapped texture is a digest mismatch, not a
    // surprise in the capture.
    const atlasSource = await relativeDescendant(base, bundle.surfaceAtlas.path, 'surfaceAtlas.path');
    if (await fileDigest(atlasSource) !== bundle.surfaceAtlas.sha256) throw new Error('surface atlas hash mismatch');
    const atlasTarget = resolve(root, bundle.surfaceAtlas.path);
    // The viewer may be written beside the bundle, in which case the atlas is already in place and
    // copying it onto itself is an EINVAL rather than a no-op.
    if (atlasTarget !== atlasSource) await cp(atlasSource, atlasTarget, { force: true });
  }
  await writeFile(output, viewerDocument(payloads, bundle));
  return output;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [first, second, third] = process.argv.slice(2);
  if (first === '--viewer') {
    if (!second || !third) throw new Error('usage: node src/index.mjs --viewer <bundle> <viewer.html>');
    console.log(await writeBrowserRuntime(second, third));
  } else {
    if (!first || !second) throw new Error('usage: node src/index.mjs <bundle> <capture-plan>');
    const manifest = await createCaptureManifest(first);
    await writeFile(second, `${JSON.stringify(manifest, null, 2)}\n`);
    console.log(second);
  }
}
