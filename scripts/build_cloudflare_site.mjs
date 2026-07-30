import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const manifestPath = path.resolve(repoRoot, option('--manifest', 'cloudflare/public-files.txt'));
const outputDir = path.resolve(repoRoot, option('--out', 'dist'));

function fail(message) {
  console.error(`BUILD_BOUNDARY_ERROR|${message}`);
  process.exit(1);
}

function readManifest(filePath) {
  if (!fs.existsSync(filePath)) fail(`manifest missing: ${path.relative(repoRoot, filePath)}`);
  const entries = fs.readFileSync(filePath, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));

  const seen = new Set();
  for (const entry of entries) {
    if (seen.has(entry)) fail(`duplicate manifest entry: ${entry}`);
    seen.add(entry);
    if (entry.includes('\\') || entry.startsWith('/') || entry.startsWith('\\') || /^[A-Za-z]:/.test(entry)) {
      fail(`manifest path is not a portable relative path: ${entry}`);
    }
    const parts = entry.split('/');
    if (parts.some((part) => !part || part === '.' || part === '..')) {
      fail(`manifest path contains unsafe segments: ${entry}`);
    }
    if (path.posix.normalize(entry) !== entry) fail(`manifest path is not normalized: ${entry}`);
  }
  if (entries.length === 0) fail('manifest is empty');
  return entries;
}

function insideRepo(candidate) {
  const root = repoRoot.endsWith(path.sep) ? repoRoot : `${repoRoot}${path.sep}`;
  return candidate === repoRoot || candidate.startsWith(root);
}

const entries = readManifest(manifestPath);
fs.rmSync(outputDir, { recursive: true, force: true });
fs.mkdirSync(outputDir, { recursive: true });

for (const entry of entries) {
  const source = path.resolve(repoRoot, ...entry.split('/'));
  if (!insideRepo(source)) fail(`source escapes repository: ${entry}`);
  if (!fs.existsSync(source)) fail(`manifest file missing: ${entry}`);
  const sourceStat = fs.lstatSync(source);
  if (!sourceStat.isFile() || sourceStat.isSymbolicLink()) fail(`manifest entry is not a regular file: ${entry}`);

  const destination = path.join(outputDir, ...entry.split('/'));
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.copyFileSync(source, destination);
}

// These are deployment metadata, not public source files. They are generated
// after the allowlist copy and contain no repository content or credentials.
fs.writeFileSync(path.join(outputDir, '404.html'), `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PlugICT — Not found</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070709;color:#f7f7f8;font:16px system-ui,sans-serif}main{text-align:center}a{color:#4ade80}</style></head><body><main><h1>Page not found</h1><p><a href="/">Back to PlugICT</a></p></main></body></html>`);
fs.writeFileSync(path.join(outputDir, '_routes.json'), `${JSON.stringify({
  version: 1,
  include: ['/api/*', '/r/*'],
  exclude: [],
}, null, 2)}\n`);
fs.writeFileSync(path.join(outputDir, '_headers'), `/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n\n/affiliate-dashboard*\n  Cache-Control: no-store\n  Referrer-Policy: no-referrer\n`);
fs.writeFileSync(path.join(outputDir, '_redirects'), '');
fs.mkdirSync(path.join(outputDir, 'affiliate'), { recursive: true });
fs.copyFileSync(path.join(outputDir, 'affiliate.html'), path.join(outputDir, 'affiliate', 'index.html'));
fs.mkdirSync(path.join(outputDir, 'affiliate-dashboard'), { recursive: true });
fs.copyFileSync(path.join(outputDir, 'affiliate-dashboard.html'), path.join(outputDir, 'affiliate-dashboard', 'index.html'));

console.log(`ALLOWLIST_BUILD|files=${entries.length}|output=${path.relative(repoRoot, outputDir)}`);
for (const entry of entries) console.log(`COPIED|${entry}`);
console.log('GENERATED|404.html|_routes.json|_headers|_redirects');
