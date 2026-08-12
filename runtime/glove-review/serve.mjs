#!/usr/bin/env node
/** Minimal localhost-only static server for the verified glove browser runtime. */
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { relative, resolve, sep } from 'node:path';

const [rootArg, portArg] = process.argv.slice(2);
if (!rootArg) throw new Error('usage: node serve.mjs <runtime-root> [port]');
const root = resolve(rootArg);
// A module script served as application/octet-stream is refused by strict MIME checking, so .mjs
// needs naming here or every module import in the viewer fails with no hint about why. PNG matters
// too: the atlas is loaded as a texture.
const contentType = (path) => path.endsWith('.html') ? 'text/html; charset=utf-8'
  : /\.(m?js)$/.test(path) ? 'text/javascript; charset=utf-8'
  : path.endsWith('.png') ? 'image/png'
  : 'application/octet-stream';
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');
    const path = resolve(root, `.${decodeURIComponent(url.pathname)}`);
    const rel = relative(root, path);
    if (rel === '' || rel === '..' || rel.startsWith(`..${sep}`)) throw new Error('not found');
    if (!(await stat(path)).isFile()) throw new Error('not found');
    response.writeHead(200, { 'content-type': contentType(path), 'cache-control': 'no-store' });
    response.end(await readFile(path));
  } catch {
    response.writeHead(404); response.end('not found');
  }
});
server.listen(Number(portArg ?? 0), '127.0.0.1', () => console.log(`http://127.0.0.1:${server.address().port}`));
process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
