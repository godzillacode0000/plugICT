import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const script = path.join(root, 'scripts', 'build_cloudflare_site.mjs');
const manifest = path.join(root, 'cloudflare', 'public-files.txt');

function run(args) {
  return spawnSync(process.execPath, [script, ...args], { cwd: root, encoding: 'utf8' });
}

function walk(directory, base = directory) {
  const result = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...walk(absolute, base));
    else result.push(path.relative(base, absolute).replaceAll(path.sep, '/'));
  }
  return result.sort();
}

const temp = mkdtempSync(path.join(os.tmpdir(), 'plugict-build-test-'));
try {
  const output = path.join(temp, 'dist');
  const result = run(['--manifest', manifest, '--out', output]);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const expected = readFileSync(manifest, 'utf8').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const actual = walk(output);
  assert.deepEqual(actual, [...expected, '404.html', '_headers', '_redirects', '_routes.json'].sort());
  assert.equal(actual.includes('store/affiliate_ledger.sqlite3'), false);
  assert.equal(actual.includes('assets/video/hero-background-source.mp4'), false);
  assert.equal(readFileSync(path.join(output, 'index.html'), 'utf8'), readFileSync(path.join(root, 'index.html'), 'utf8'));

  const malformed = path.join(temp, 'malformed.txt');
  writeFileSync(malformed, `${readFileSync(manifest, 'utf8')}\n../store/secret.txt\n`);
  const rejectedParent = run(['--manifest', malformed, '--out', path.join(temp, 'bad-parent')]);
  assert.notEqual(rejectedParent.status, 0);
  assert.match(rejectedParent.stderr, /parent traversal|unsafe/i);

  writeFileSync(malformed, `${readFileSync(manifest, 'utf8')}\nmissing-file.txt\n`);
  const rejectedMissing = run(['--manifest', malformed, '--out', path.join(temp, 'bad-missing')]);
  assert.notEqual(rejectedMissing.status, 0);
  assert.match(rejectedMissing.stderr, /missing/i);
} finally {
  rmSync(temp, { recursive: true, force: true });
}

console.log('build-boundary|PASS');
