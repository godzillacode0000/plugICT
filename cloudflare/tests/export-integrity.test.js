import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const repoDir = fileURLToPath(new URL('../../', import.meta.url));

test('vault export manifest and R2 destination fail closed', () => {
  const python = process.platform === 'win32' ? 'python' : 'python3';
  const result = spawnSync(python, ['scripts/test_vault_export_integrity.py'], {
    cwd: repoDir,
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stderr, /Ran \d+ tests/);
  assert.match(result.stderr, /OK/);
});
