import * as THREE from 'three';
import './style.css';
import {
  createGeneratedKnife,
  createGeneratedKnifeEnvironment,
  createGeneratedFamily,
  type GeneratedFamilySpec,
  type GeneratedKnifeSpec,
} from './generatedKnifeFactory';

type ProjectionStatus = 'ready' | 'request-input' | 'fallback';
type Vector3Tuple = readonly [number, number, number];

type SourceView = Readonly<{
  role?: string;
  path: string;
  deLitPath?: string;
  width?: number;
  height?: number;
}>;

type IntakeManifest = Readonly<{
  schemaVersion: number;
  state: string;
  itemFamily: string;
  subtype: string;
  route: string;
  exactnessTier: string;
  componentAdapter: string;
  sourceViews: readonly SourceView[];
  camera?: Readonly<{
    projectionMode?: 'perspective-camera-projection' | 'orthographic-front-projection';
    fovDegrees?: number;
    position?: Vector3Tuple;
    target?: Vector3Tuple;
  }>;
  environment?: Readonly<{ available: boolean; hash: string }>;
}>;

type PreviewSpec = Readonly<{
  kind: 'knife' | 'pistol' | 'rifle';
  itemFamily: string;
  subtype: string;
  adapterId: string;
  materialChannels: readonly string[];
  environmentAvailable: boolean;
  genericComponents: readonly JsonRecord[];
}>;

type ReviewArtifact = Readonly<{
  family: string;
  subtype: string;
  adapterId: string;
  contractVersion: string;
  fixtureId: string;
  manifestReviewArtifact: Readonly<{ projectionCoverage: number; bakedTexture: string; coverageMask: string; status: ProjectionStatus }>;
  projectionStatus: ProjectionStatus;
  projectionCoverage: number;
  bakedTexture: string;
  coverageMask: string;
  captures: Readonly<Record<string, string>>;
  materialChannels: readonly string[];
  environment: Readonly<{ available: boolean; hash: string }>;
  renderer: Readonly<{ three: string; colorSpace: string; toneMapping: string }>;
}>;

type JsonRecord = Readonly<Record<string, unknown>>;
let currentPhase = 'boot';

declare global {
  interface Window {
    __CS2_REVIEW_ARTIFACT__?: ReviewArtifact;
  }
}

class PreviewInputError extends Error {
  public readonly code: 'invalid-manifest' | 'invalid-spec' | 'missing-projection-input';

  public constructor(code: PreviewInputError['code'], message: string) {
    super(message);
    this.name = 'PreviewInputError';
    this.code = code;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringField(record: JsonRecord, key: string): string | undefined {
  const value = record[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function tupleField(record: JsonRecord, key: string): Vector3Tuple | undefined {
  const value = record[key];
  if (!Array.isArray(value) || value.length !== 3 || !value.every((item) => typeof item === 'number')) return undefined;
  const first = value[0];
  const second = value[1];
  const third = value[2];
  return typeof first === 'number' && typeof second === 'number' && typeof third === 'number' ? [first, second, third] : undefined;
}

function parseManifest(value: unknown): IntakeManifest {
  if (!isRecord(value)) throw new PreviewInputError('invalid-manifest', 'cs2-intake.json must be an object');
  const sourceViewsValue = value.sourceViews;
  if (!Array.isArray(sourceViewsValue) || sourceViewsValue.length === 0) {
    throw new PreviewInputError('missing-projection-input', 'manifest has no sourceViews');
  }
  const sourceViews: SourceView[] = [];
  for (const sourceValue of sourceViewsValue) {
    if (!isRecord(sourceValue)) throw new PreviewInputError('invalid-manifest', 'sourceViews contains a non-object');
    const path = stringField(sourceValue, 'path');
    const role = stringField(sourceValue, 'role');
    if (!path) throw new PreviewInputError('missing-projection-input', 'source view has no path');
    const deLitPath = stringField(sourceValue, 'deLitPath');
    sourceViews.push({
      ...(role ? { role } : {}),
      path,
      ...(deLitPath ? { deLitPath } : {}),
      ...(typeof sourceValue.width === 'number' ? { width: sourceValue.width } : {}),
      ...(typeof sourceValue.height === 'number' ? { height: sourceValue.height } : {}),
    });
  }
  const cameraValue = value.camera;
  const position = isRecord(cameraValue) ? tupleField(cameraValue, 'position') : undefined;
  const target = isRecord(cameraValue) ? tupleField(cameraValue, 'target') : undefined;
  const camera: IntakeManifest['camera'] = isRecord(cameraValue)
    ? {
        ...(cameraValue.projectionMode === 'orthographic-front-projection' ? { projectionMode: cameraValue.projectionMode } : {}),
        ...(cameraValue.projectionMode === 'perspective-camera-projection' ? { projectionMode: cameraValue.projectionMode } : {}),
        ...(typeof cameraValue.fovDegrees === 'number' ? { fovDegrees: cameraValue.fovDegrees } : {}),
        ...(position ? { position } : {}),
        ...(target ? { target } : {}),
      }
    : undefined;
  const environmentValue = value.environment;
  const environment = isRecord(environmentValue)
    ? { available: environmentValue.available !== false, hash: stringField(environmentValue, 'hash') ?? 'runtime-room-environment' }
    : { available: true, hash: 'runtime-room-environment' };
  const itemFamily = stringField(value, 'itemFamily') ?? (isRecord(value.resolvedIdentity) ? stringField(value.resolvedIdentity, 'itemFamily') : undefined) ?? 'unknown';
  const componentAdapter = stringField(value, 'componentAdapter') ?? (itemFamily === 'knife' ? 'cs2-knife-v1' : undefined);
  if (!componentAdapter) throw new PreviewInputError('invalid-manifest', `manifest has no adapter for ${itemFamily}`);
  return {
    schemaVersion: typeof value.schemaVersion === 'number' ? value.schemaVersion : 0,
    state: stringField(value, 'state') ?? 'request-input',
    itemFamily,
    subtype: stringField(value, 'subtype') ?? (isRecord(value.resolvedIdentity) ? stringField(value.resolvedIdentity, 'subtype') : undefined) ?? 'unknown',
    componentAdapter,
    route: stringField(value, 'route') ?? 'unknown',
    exactnessTier: stringField(value, 'exactnessTier') ?? 'unknown',
    sourceViews,
    ...(camera ? { camera } : {}),
    environment,
  };
}

function parseSpec(value: unknown): PreviewSpec {
  if (!isRecord(value)) throw new PreviewInputError('invalid-spec', 'spec must be an object');
  const components = Array.isArray(value.componentTree) ? value.componentTree.filter(isRecord) : [];
  const intake = isRecord(value.cs2Intake) ? value.cs2Intake : undefined;
  const family = stringField(value, 'itemFamily') ?? (intake ? stringField(intake, 'itemFamily') : undefined);
  const subtype = stringField(value, 'subtype') ?? (intake ? stringField(intake, 'subtype') : undefined);
  const adapterId = stringField(value, 'componentAdapter') ?? (intake ? stringField(intake, 'componentAdapter') : undefined) ?? (family === 'knife' ? 'cs2-knife-v1' : undefined);
  if (!family || !subtype || !adapterId) throw new PreviewInputError('invalid-spec', 'family spec is missing identity metadata');
  const common = { materialChannels: ['albedo', 'roughness', 'metalness', 'normal', 'ao'], environmentAvailable: value.environmentAvailable !== false, genericComponents: components, itemFamily: family, subtype, adapterId } as const;
  switch (family) {
    case 'knife':
      if (adapterId !== 'cs2-knife-v1') throw new PreviewInputError('invalid-spec', 'knife adapter mismatch');
      return { ...common, kind: 'knife' };
    case 'pistol':
      if (adapterId !== 'cs2-pistol-v1') throw new PreviewInputError('invalid-spec', 'pistol adapter mismatch');
      return { ...common, kind: 'pistol' };
    case 'rifle':
      if (adapterId !== 'cs2-rifle-v1') throw new PreviewInputError('invalid-spec', 'rifle adapter mismatch');
      return { ...common, kind: 'rifle' };
    default:
      throw new PreviewInputError('invalid-spec', `unsupported CS2 family: ${family}`);
  }
}

async function loadJson(path: string): Promise<unknown> {
  const response = await fetch(path);
  if (!response.ok) throw new PreviewInputError('invalid-manifest', `${path} returned HTTP ${response.status}`);
  return response.json();
}

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`preview DOM contract is incomplete: ${selector}`);
  return element;
}

function makeProjectorCamera(manifest: IntakeManifest): THREE.PerspectiveCamera {
  const camera = new THREE.PerspectiveCamera(manifest.camera?.fovDegrees ?? 34, 1, 0.01, 100);
  camera.position.fromArray(manifest.camera?.position ?? [-0.35, 0.15, 4.5]);
  camera.lookAt(new THREE.Vector3().fromArray(manifest.camera?.target ?? [0, 0, 0]));
  camera.updateProjectionMatrix();
  return camera;
}

function projectiveTextureMaterial(texture: THREE.Texture, projector: THREE.Camera): THREE.ShaderMaterial {
  const projectorMatrix = new THREE.Matrix4().multiplyMatrices(projector.projectionMatrix, projector.matrixWorldInverse);
  return new THREE.ShaderMaterial({
    uniforms: { projectedTexture: { value: texture }, projectorMatrix: { value: projectorMatrix } },
    vertexShader: `
      uniform mat4 projectorMatrix;
      varying vec4 projectedPosition;
      void main() {
        vec4 worldPosition = modelMatrix * vec4(position, 1.0);
        projectedPosition = projectorMatrix * worldPosition;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D projectedTexture;
      varying vec4 projectedPosition;
      void main() {
        vec3 ndc = projectedPosition.xyz / max(projectedPosition.w, 0.0001);
        vec2 uv = ndc.xy * 0.5 + 0.5;
        if (projectedPosition.w <= 0.0 || uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard;
        gl_FragColor = texture2D(projectedTexture, uv);
      }
    `,
  });
}

function replaceProjectionMaterial(model: THREE.Object3D, material: THREE.ShaderMaterial): void {
  model.traverse((child) => {
    if (child instanceof THREE.Mesh) child.material = material;
  });
}

function bakeUv(model: THREE.Object3D, source: THREE.Texture, projector: THREE.Camera, renderer: THREE.WebGLRenderer, size: number): { texture: THREE.WebGLRenderTarget; coverage: number } {
  const target = new THREE.WebGLRenderTarget(size, size, { colorSpace: THREE.SRGBColorSpace });
  const coverageTarget = new THREE.WebGLRenderTarget(size, size);
  const bakeScene = new THREE.Scene();
  const projectorMatrix = new THREE.Matrix4().multiplyMatrices(projector.projectionMatrix, projector.matrixWorldInverse);
  model.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return;
    const material = new THREE.ShaderMaterial({
      uniforms: { projectedTexture: { value: source }, projectorMatrix: { value: projectorMatrix } },
      vertexShader: `uniform mat4 projectorMatrix; varying vec4 projectedPosition; void main() { projectedPosition = projectorMatrix * modelMatrix * vec4(position, 1.0); gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0); }`,
      fragmentShader: `uniform sampler2D projectedTexture; varying vec4 projectedPosition; void main() { vec3 ndc = projectedPosition.xyz / max(projectedPosition.w, 0.0001); vec2 uv = ndc.xy * 0.5 + 0.5; if (projectedPosition.w <= 0.0 || uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard; gl_FragColor = texture2D(projectedTexture, uv); }`,
    });
    const clone = new THREE.Mesh(child.geometry, material);
    clone.matrixAutoUpdate = false;
    clone.matrix.copy(child.matrixWorld);
    bakeScene.add(clone);
  });
  const bakeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const previousTarget = renderer.getRenderTarget();
  renderer.setRenderTarget(target);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  renderer.render(bakeScene, bakeCamera);
  renderer.setRenderTarget(coverageTarget);
  renderer.clear();
  renderer.render(bakeScene, bakeCamera);
  const pixels = new Uint8Array(size * size * 4);
  renderer.readRenderTargetPixels(coverageTarget, 0, 0, size, size, pixels);
  let covered = 0;
  for (let index = 3; index < pixels.length; index += 4) {
    const alpha = pixels[index];
    if (alpha !== undefined && alpha > 0) covered += 1;
  }
  renderer.setRenderTarget(previousTarget);
  coverageTarget.dispose();
  bakeScene.traverse((child) => { if (child instanceof THREE.Mesh && child.material instanceof THREE.Material) child.material.dispose(); });
  return { texture: target, coverage: covered / (size * size) };
}

function capture(renderer: THREE.WebGLRenderer, label: string): string {
  const data = renderer.domElement.toDataURL('image/png');
  const anchor = document.createElement('a');
  anchor.download = `${label}.png`;
  anchor.href = data;
  anchor.dataset.capture = label;
  return data;
}

async function start(): Promise<void> {
  currentPhase = 'dom';
  const canvas = requiredElement<HTMLCanvasElement>('#preview');
  const status = requiredElement<HTMLParagraphElement>('#status');
  const state = requiredElement<HTMLSpanElement>('#state');
  const tier = requiredElement<HTMLSpanElement>('#tier');
  const coverageLabel = requiredElement<HTMLSpanElement>('#coverage');
  const artifactLink = requiredElement<HTMLAnchorElement>('#download-artifact');
  currentPhase = 'renderer';
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.shadowMap.enabled = true;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#121316');
  currentPhase = 'manifest';
  const manifest = parseManifest(await loadJson('/cs2-intake.json'));
  currentPhase = 'spec';
  const specPath = manifest.itemFamily === 'knife' ? '/cs2-knife.spec.json' : `/cs2-${manifest.itemFamily}.spec.json`;
  const spec = parseSpec(await loadJson(specPath));
  if (spec.itemFamily !== manifest.itemFamily || spec.subtype !== manifest.subtype || spec.adapterId !== manifest.componentAdapter) {
    throw new PreviewInputError('invalid-spec', 'manifest and spec family identity do not match');
  }
  const camera = makeProjectorCamera(manifest);
  const sourceView = manifest.sourceViews.find((view) => view.role === 'primary') ?? manifest.sourceViews[0];
  if (!sourceView) throw new PreviewInputError('missing-projection-input', 'manifest source view disappeared after parsing');
  currentPhase = 'source-image';
  const source = await new THREE.TextureLoader().loadAsync(sourceView.path);
  source.colorSpace = THREE.SRGBColorSpace;
  source.anisotropy = renderer.capabilities.getMaxAnisotropy();
  let model: THREE.Group;
  switch (spec.kind) {
    case 'knife':
      model = createGeneratedKnife({ materialChannels: spec.materialChannels, environmentAvailable: spec.environmentAvailable } satisfies GeneratedKnifeSpec);
      break;
    case 'pistol':
    case 'rifle':
      model = createGeneratedFamily({ family: spec.kind, materialChannels: spec.materialChannels } satisfies GeneratedFamilySpec);
      break;
    default:
      throw new PreviewInputError('invalid-spec', 'unsupported preview factory');
  }
  scene.add(model);
  scene.add(createGeneratedKnifeEnvironment());
  const projectorMaterial = projectiveTextureMaterial(source, camera);
  replaceProjectionMaterial(model, projectorMaterial);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(2.8, 64), new THREE.MeshStandardMaterial({ color: '#1b1d23', roughness: 0.86 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.55; floor.receiveShadow = true; scene.add(floor);
  currentPhase = 'uv-bake';
  const bake = bakeUv(model, source, camera, renderer, 256);
  const captures: Record<string, string> = {};
  const render = (yaw: number, pitch: number, label: string): void => { model.rotation.set(pitch, yaw, -0.12); renderer.render(scene, camera); captures[label] = capture(renderer, label); };
  const resize = (): void => { const height = Math.max(420, window.innerHeight - 160); renderer.setSize(window.innerWidth, height, false); camera.aspect = window.innerWidth / height; camera.updateProjectionMatrix(); render(0, 0, 'fixed-view'); };
  window.addEventListener('resize', resize);
  document.querySelector('#fixed-view')?.addEventListener('click', () => render(0, 0, 'fixed-view'));
  document.querySelector('#orbit-a')?.addEventListener('click', () => render(0.55, 0.18, 'orbit-a'));
  document.querySelector('#orbit-b')?.addEventListener('click', () => render(-0.7, -0.12, 'orbit-b'));
  resize();
  render(0.55, 0.18, 'orbit-a');
  render(-0.7, -0.12, 'orbit-b');
  render(0, 0, 'fixed-view');
  const artifact: ReviewArtifact = {
    family: manifest.itemFamily,
    subtype: manifest.subtype,
    adapterId: manifest.componentAdapter,
    contractVersion: '1',
    fixtureId: `cs2-${manifest.itemFamily}-front-v1`,
    projectionStatus: manifest.state === 'proceed' && manifest.route === 'reference-projection' ? 'ready' : 'request-input',
    projectionCoverage: bake.coverage,
    bakedTexture: 'runtime://uv-render-target/albedo',
    coverageMask: 'runtime://uv-render-target/coverage',
    manifestReviewArtifact: {
      projectionCoverage: bake.coverage,
      bakedTexture: 'runtime://uv-render-target/albedo',
      coverageMask: 'runtime://uv-render-target/coverage',
      status: manifest.state === 'proceed' && manifest.route === 'reference-projection' ? 'ready' : 'request-input',
    },
    captures,
    materialChannels: spec.materialChannels,
    environment: manifest.environment ?? { available: true, hash: 'runtime-room-environment' },
    renderer: { three: '0.180.0', colorSpace: 'sRGB', toneMapping: 'ACESFilmicToneMapping' },
  };
  window.__CS2_REVIEW_ARTIFACT__ = artifact;
  artifactLink.href = URL.createObjectURL(new Blob([JSON.stringify(artifact, null, 2)], { type: 'application/json' }));
  artifactLink.download = 'cs2-review-artifact.json';
  artifactLink.removeAttribute('aria-disabled');
  status.textContent = `${manifest.itemFamily} / ${manifest.subtype} · ${manifest.route}`;
  state.textContent = `state: ${manifest.state}`;
  tier.textContent = `tier: ${manifest.exactnessTier}`;
  coverageLabel.textContent = `projection coverage: ${bake.coverage.toFixed(3)}`;
}

start().catch((error: unknown) => {
  const status = document.querySelector<HTMLParagraphElement>('#status');
  const state = document.querySelector<HTMLSpanElement>('#state');
  if (status) status.textContent = error instanceof Error ? `${error.message} [${currentPhase}]` : `preview failed: ${String(error)} [${currentPhase}]`;
  if (state) state.textContent = error instanceof PreviewInputError && error.code === 'missing-projection-input' ? 'state: request-input' : 'state: error';
});
