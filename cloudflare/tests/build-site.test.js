const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..', '..');
const builder = path.join(root, 'scripts', 'build_cloudflare_site.mjs');
const manifest = path.join(root, 'cloudflare', 'public-files.txt');
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'plugict-build-boundary-'));

function run(manifestPath, outputDir) {
  return spawnSync(process.execPath, [builder, '--manifest', manifestPath, '--out', outputDir], {
    cwd: root,
    encoding: 'utf8',
  });
}

function walk(directory, base = directory) {
  const result = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...walk(absolute, base));
    else result.push(path.relative(base, absolute).replaceAll(path.sep, '/'));
  }
  return result.sort();
}

function writeManifest(name, lines) {
  const file = path.join(tempRoot, name);
  fs.writeFileSync(file, `${lines.join('\n')}\n`);
  return file;
}

try {
  const output = path.join(tempRoot, 'dist');
  const good = run(manifest, output);
  assert.equal(good.status, 0, good.stderr);

  const expected = fs.readFileSync(manifest, 'utf8').split(/\r?\n/).filter(Boolean).sort();
  const actual = walk(output);
  assert.deepEqual(actual, [...expected, '_headers', '_redirects', '_routes.json'].sort());
  assert.equal(JSON.parse(fs.readFileSync(path.join(output, '_routes.json'), 'utf8')).include[0], '/api/*');
  assert.equal(fs.existsSync(path.join(output, 'store')), false);
  assert.equal(fs.existsSync(path.join(output, 'scripts')), false);
  assert.equal(fs.existsSync(path.join(output, 'tests')), false);
  assert.equal(fs.existsSync(path.join(output, 'assets', 'video', 'hero-background-source.mp4')), false);
  assert.equal(fs.existsSync(path.join(output, 'assets', 'video', 'knowledge-graph', 'index.html')), false);

  const missing = [...expected, 'missing-file.html'];
  assert.notEqual(run(writeManifest('missing.txt', missing), path.join(tempRoot, 'missing-out')).status, 0);
  assert.notEqual(run(writeManifest('parent.txt', ['../README.md']), path.join(tempRoot, 'parent-out')).status, 0);
  assert.notEqual(run(writeManifest('absolute.txt', ['/etc/passwd']), path.join(tempRoot, 'absolute-out')).status, 0);
  assert.notEqual(run(writeManifest('duplicate.txt', ['index.html', 'index.html']), path.join(tempRoot, 'duplicate-out')).status, 0);

  console.log(`BUILD_BOUNDARY_TEST|PASS|manifest=${expected.length}|generated=3`);
} finally {
  fs.rmSync(tempRoot, { recursive: true, force: true });
}
