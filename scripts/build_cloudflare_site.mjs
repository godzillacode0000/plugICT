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
fs.writeFileSync(path.join(outputDir, '_routes.json'), `${JSON.stringify({
  version: 1,
  include: ['/api/*'],
  exclude: [],
}, null, 2)}\n`);
fs.writeFileSync(path.join(outputDir, '_headers'), `/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n\n/affiliate-dashboard*\n  Cache-Control: no-store\n  Referrer-Policy: no-referrer\n`);
fs.writeFileSync(path.join(outputDir, '_redirects'), `/affiliate              /affiliate.html              200\n/affiliate-dashboard    /affiliate-dashboard.html    200\n`);

console.log(`ALLOWLIST_BUILD|files=${entries.length}|output=${path.relative(repoRoot, outputDir)}`);
for (const entry of entries) console.log(`COPIED|${entry}`);
console.log('GENERATED|_routes.json|_headers|_redirects');
