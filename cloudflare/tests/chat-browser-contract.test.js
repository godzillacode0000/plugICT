import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const chatPath = new URL('../../chat/index.html', import.meta.url);
const bootstrapPath = new URL('../../assets/chat-bootstrap.js', import.meta.url);
const sdkPath = new URL('../../assets/vendor/supabase.js', import.meta.url);
const licensePath = new URL('../../assets/vendor/supabase.LICENSE.txt', import.meta.url);
const manifestPath = new URL('../public-files.txt', import.meta.url);

function relativeLuminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map((part) => Number.parseInt(part, 16) / 255);
  const [red, green, blue] = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
}

function contrastRatio(foreground, background) {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

test('chat page exposes the complete auth and chat DOM contract', () => {
  const chat = readFileSync(chatPath, 'utf8');
  for (const hook of [
    'data-auth-gate',
    'data-google-signin',
    'data-chat-dashboard',
    'data-user-email',
    'data-signout',
    'data-chat-status',
    'data-messages',
    'data-chat-form',
    'data-question',
    'data-plan',
  ]) {
    assert.match(chat, new RegExp(hook));
  }
  assert.match(chat, /https:\/\/tamevojmkrmttutkkuvo\.supabase\.co/);
  assert.match(chat, /supabasePublishableKey:\s*['"]sb_publishable_/);
  assert.doesNotMatch(chat, /service_role|client_secret|oauth_secret/i);
  assert.match(chat, /\/assets\/vendor\/supabase\.js/);
  assert.match(chat, /\/assets\/chat-bootstrap\.js/);
});

test('pinned Supabase SDK, licence, and browser bootstrap are published', () => {
  assert.equal(existsSync(sdkPath), true, 'vendored Supabase SDK must exist');
  assert.equal(existsSync(licensePath), true, 'Supabase MIT licence must exist');
  assert.equal(existsSync(bootstrapPath), true, 'chat bootstrap must exist');

  const manifest = readFileSync(manifestPath, 'utf8').split(/\r?\n/);
  for (const file of [
    'assets/chat-app.js',
    'assets/chat-bootstrap.js',
    'assets/vendor/supabase.js',
    'assets/vendor/supabase.LICENSE.txt',
  ]) {
    assert.equal(manifest.includes(file), true, `${file} must be published`);
  }
  const sdkSha256 = createHash('sha256').update(readFileSync(sdkPath)).digest('hex');
  assert.equal(
    sdkSha256,
    '04b957f2563a40dcb02b1d9d6f7a7a23973bf8ebe4c1435be5feaf24bff91134',
    'vendored SDK must be byte-identical to @supabase/supabase-js@2.112.2 dist/umd/supabase.js',
  );
});

test('browser bootstrap never persists or renders access tokens', () => {
  assert.equal(existsSync(bootstrapPath), true, 'chat bootstrap must exist');
  const bootstrap = readFileSync(bootstrapPath, 'utf8');
  assert.doesNotMatch(bootstrap, /localStorage\.setItem|sessionStorage\.setItem/);
  assert.doesNotMatch(bootstrap, /innerHTML\s*=/);
  assert.match(bootstrap, /createChatController/);
  assert.match(bootstrap, /textContent/);
});

test('source cards render the server-verified transcript quote as text', () => {
  const bootstrap = readFileSync(bootstrapPath, 'utf8');
  const chat = readFileSync(chatPath, 'utf8');
  assert.match(bootstrap, /source\.quote/);
  assert.match(bootstrap, /source-quote/);
  assert.match(chat, /\.source-quote\{/);
  assert.doesNotMatch(bootstrap, /innerHTML\s*=/);
});

test('mobile dashboard keeps account identity and sign-out available', () => {
  const chat = readFileSync(chatPath, 'utf8');
  const bootstrap = readFileSync(bootstrapPath, 'utf8');
  assert.match(chat, /data-mobile-account/);
  assert.equal((chat.match(/data-user-email/g) || []).length, 2);
  assert.equal((chat.match(/data-signout/g) || []).length, 2);
  assert.match(bootstrap, /querySelectorAll\('\[data-user-email\]'\)/);
  assert.match(bootstrap, /querySelectorAll\('\[data-signout\]'\)/);
});

test('small muted labels meet WCAG AA contrast on chat surfaces', () => {
  const chat = readFileSync(chatPath, 'utf8');
  const match = chat.match(/--muted2:#([0-9a-f]{6})/i);
  assert.ok(match, 'chat page must define the muted label token');
  const muted = match[1];
  for (const background of ['111111', '0d0d0d']) {
    assert.ok(
      contrastRatio(muted, background) >= 4.5,
      `#${muted} must have at least 4.5:1 contrast on #${background}`,
    );
  }
});

test('composer placeholder and Ask text meet WCAG AA across their surfaces', () => {
  const chat = readFileSync(chatPath, 'utf8');
  const placeholder = chat.match(/textarea::placeholder\{color:#([0-9a-f]{6})\}/i)?.[1];
  const buttonText = chat.match(/\.composer button\{[^}]*color:#([0-9a-f]{6})/i)?.[1];
  assert.ok(placeholder, 'composer placeholder must use an explicit six-digit colour');
  assert.ok(buttonText, 'Ask button must use an explicit six-digit text colour');
  assert.ok(contrastRatio(placeholder, '171717') >= 4.5, 'placeholder must reach 4.5:1 on composer background');
  for (const orange of ['ff6b1a', 'ff8a3d']) {
    assert.ok(
      contrastRatio(buttonText, orange) >= 4.5,
      `Ask text #${buttonText} must reach 4.5:1 on gradient endpoint #${orange}`,
    );
  }
});
