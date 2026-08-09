import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const root = new URL('../../', import.meta.url);
const landingPath = new URL('../../index.html', import.meta.url);
const chatPath = new URL('../../chat/index.html', import.meta.url);
const manifestPath = new URL('../public-files.txt', import.meta.url);

function count(haystack, needle) {
  return haystack.split(needle).length - 1;
}

test('landing Try PlugICT CTAs route to the isolated chat dashboard', () => {
  const landing = readFileSync(landingPath, 'utf8');
  assert.equal(count(landing, 'Try PlugICT'), 3);
  assert.equal(count(landing, 'href="/chat/"'), 3);
});

test('chat dashboard is a published auth-gated route', () => {
  assert.equal(existsSync(chatPath), true, 'chat/index.html must exist');
  const chat = readFileSync(chatPath, 'utf8');
  assert.match(chat, /data-auth-gate/);
  assert.match(chat, /Sign in with Google/);

  const manifest = readFileSync(manifestPath, 'utf8').split(/\r?\n/);
  assert.equal(manifest.includes('chat/index.html'), true);
});
