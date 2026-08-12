import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const output = resolve(new URL('./dist/glove-review-runtime.json', import.meta.url).pathname);
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify({
  version: 'glove-review-runtime.v1',
  deterministic: true,
  bundleHashVerification: true,
  cameraContract: ['dorsal', 'palmar', 'thumb-side-profile', 'three-quarter', 'orbit-a', 'orbit-b'],
  settleFrames: 2,
}, null, 2) + '\n');
console.log(output);
