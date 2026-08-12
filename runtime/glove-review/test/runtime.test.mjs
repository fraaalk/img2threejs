import test from 'node:test';
import assert from 'node:assert/strict';
import { createCaptureManifest, loadAndVerifyBundle, REQUIRED_CAPTURE_ROLES } from '../src/index.mjs';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function sha(value) {
  return createHash('sha256').update(value).digest('hex');
}

test('runtime contract declares required views and deterministic capture metadata', async () => {
  assert.equal(REQUIRED_CAPTURE_ROLES.length, 5);
  assert.equal(typeof createCaptureManifest, 'function');
});

test('runtime verifies the exact content-addressed bundle and binds captures to its root digest', async () => {
  const temp = await mkdtemp(join(tmpdir(), 'img2-glove-runtime-'));
  const factory = "export const modelBundleVersion = 'glove-model-bundle.v2';\nexport function createGloveModel(bundle, payloads) { return { type: 'Group', meshes: payloads }; }\n";
  const payload = JSON.stringify({ id: 'mesh-left', vertices: [[0,0,0],[1,0,0],[0,1,0]], indices: [[0,1,2]], normals: [[0,0,1],[0,0,1],[0,0,1]] });
  await writeFile(join(temp, 'factory.mjs'), factory);
  await writeFile(join(temp, 'mesh.json'), payload);
  const bundle = {
    version: 'glove-model-bundle.v2',
    factoryModule: { path: 'factory.mjs', sha256: sha(factory) },
    payloads: [{ id: 'mesh-left', path: 'mesh.json', sha256: sha(payload) }],
    sceneRoot: 'test',
  };
  bundle.rootDigest = sha(canonical(bundle));
  const bundlePath = join(temp, 'glove-model-bundle.v2.json');
  await writeFile(bundlePath, JSON.stringify(bundle));
  const verified = await loadAndVerifyBundle(bundlePath);
  const capture = await createCaptureManifest(bundlePath);
  assert.equal(verified.bundle.rootDigest, bundle.rootDigest);
  assert.equal(capture.modelBundleDigest, bundle.rootDigest);
  assert.equal(capture.captures.length, 7);
  assert.equal(capture.finalized, false);
});
