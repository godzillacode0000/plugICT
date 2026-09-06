import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, statSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const read = (name) => readFileSync(resolve(root, name), "utf8");
const html = read("index.html").replace(/\s+/g, " ");
const css = read("assets/landing.css");
const script = read("assets/landing.js");
const attribution = read("assets/affiliate-attribution.js");
const manifest = new Set(
  read("cloudflare/public-files.txt").trim().split(/\r?\n/),
);
const checkout = "https://buy.stripe.com/7sY14ob6qcTC057cTy6Ri02";

test("every local landing asset, CSS URL, and page link is deployed", () => {
  for (const [, raw] of html.matchAll(/(?:href|src|poster)="([^"]+)"/g)) {
    if (/^(?:https?:|mailto:|#)/.test(raw)) continue;
    const path = raw.split("?")[0];
    assert.ok(manifest.has(path), `Missing allowlist entry: ${path}`);
    assert.ok(statSync(resolve(root, path)).size > 0, `Empty asset: ${path}`);
  }
  for (const [, url] of css.matchAll(/url\(['"]?([^)'"\s]+)['"]?\)/g)) {
    assert.ok(
      manifest.has(`assets/${url}`),
      `CSS asset missing from allowlist: ${url}`,
    );
  }
  assert.equal(manifest.has("design-qa.md"), false);
  assert.equal(manifest.has("scripts/responsive_qa.html"), false);
  assert.equal(manifest.has("scripts/preview_site.mjs"), false);
});

test("all fragment links and ARIA control references resolve to unique IDs", () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "Duplicate IDs");
  for (const [, id] of html.matchAll(/href="#([^"]+)"/g))
    assert.ok(ids.includes(id), `Missing fragment ${id}`);
  for (const [, names] of html.matchAll(
    /aria-(?:controls|labelledby)="([^"]+)"/g,
  )) {
    names
      .split(" ")
      .forEach((id) =>
        assert.ok(ids.includes(id), `Missing ARIA target ${id}`),
      );
  }
});

test("critical content is usable without JavaScript and motion is optional", () => {
  assert.equal((html.match(/<h1\b/g) || []).length, 1);
  assert.match(html, /href="#main"/);
  assert.match(html, /data-buy-link[^>]+https:\/\/buy\.stripe\.com\//);
  assert.match(html, /<video[^>]+controls[^>]+preload="none"/);
  assert.doesNotMatch(html, /\bautoplay\b/);
  assert.ok((html.match(/<details>/g) || []).length >= 7);
  assert.match(html, /not a live AI chat/);
  assert.match(html, /within 24 hours/);
  assert.match(html, /model fees depend on your choice/);
  assert.doesNotMatch(css, /(?:data-reveal|data-hero)[^{]*\{[^}]*opacity:\s*0/);
  assert.match(
    script,
    /if \(!window\.gsap \|\| !window\.ScrollTrigger\) return/,
  );
  assert.match(script, /prefers-reduced-motion: no-preference/);
  assert.ok(
    html.indexOf("assets/affiliate-attribution.js") <
      html.indexOf("assets/landing.js"),
  );
});

class Element {
  constructor(attrs = {}) {
    this.attrs = attrs;
    this.dataset = {};
    this.events = {};
    this.textContent = "";
    this.classes = new Set();
    this.children = {};
    this.hidden = true;
    this.classList = {
      add: (name) => this.classes.add(name),
      remove: (name) => this.classes.delete(name),
      toggle: (name, active) =>
        active ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  setAttribute(name, value) {
    this.attrs[name] = value;
  }
  getAttribute(name) {
    return this.attrs[name] ?? null;
  }
  addEventListener(name, callback) {
    this.events[name] = callback;
  }
  querySelector(name) {
    return this.children[name];
  }
  querySelectorAll(name) {
    return this.children[name] || [];
  }
  contains(target) {
    return target === this;
  }
  focus() {
    this.focused = true;
  }
  click() {
    this.events.click?.({ target: this });
  }
}

function page({ query = "", stored = null, storageBlocked = false, reduced = false, withMotion = false } = {}) {
  const selectors = {};
  for (const name of [
    ".site-header",
    ".site-nav",
    ".menu-toggle",
    "#example-question",
    "#example-title",
    "#example-answer",
    "#example-timestamp",
    "#example-source",
    "#product-video",
    "#demo-caption",
    "#download-demo",
  ])
    selectors[name] = new Element();
  const header = selectors[".site-header"],
    menu = selectors[".site-nav"],
    toggle = selectors[".menu-toggle"];
  toggle.children.img = new Element();
  menu.children.a = [new Element()];
  const buy = new Element();
  buy.href = checkout;
  const examples = ["definition", "time", "source"].map((key) => {
    const e = new Element();
    e.dataset.example = key;
    return e;
  });
  const videos = ["desktop", "phone"].map((key) => {
    const e = new Element({ "aria-pressed": String(key === "desktop") });
    e.dataset.video = key;
    return e;
  });
  const video = selectors["#product-video"];
  video.children.a = new Element();
  video.children.source = ["video/webm", "video/mp4"].map((type) =>
    Object.assign(new Element(), { type }),
  );
  video.pause = () => {
    video.paused = true;
  };
  video.load = () => {
    video.loads = (video.loads || 0) + 1;
  };
  const groups = {
    "[data-year]": [new Element()],
    "[data-buy-link]": [buy],
    "[data-example]": examples,
    "[data-video]": videos,
  };
  const documentEvents = {};
  const document = {
    querySelector: (name) => selectors[name],
    querySelectorAll: (name) => groups[name] || [],
    addEventListener: (name, fn) => {
      documentEvents[name] = fn;
    },
  };
  const window = {
    location: { search: query },
    matchMedia: () => ({ matches: reduced, addEventListener() {} }),
    addEventListener() {},
    scrollY: 0,
  };
  const animations = [];
  if (withMotion) {
    window.ScrollTrigger = { refresh() {} };
    window.gsap = {
      registerPlugin() {},
      matchMedia: () => ({ add: (query, callback) => {
        assert.equal(query, '(prefers-reduced-motion: no-preference)');
        if (!reduced) callback();
      } }),
      from: (...args) => animations.push(args),
      to: (...args) => animations.push(args),
      fromTo: (...args) => animations.push(args),
    };
  }
  let current = stored;
  const localStorage = {
    getItem: () => {
      if (storageBlocked) throw Error("blocked");
      return current;
    },
    setItem: (_, value) => {
      if (storageBlocked) throw Error("blocked");
      current = value;
    },
    removeItem: () => {
      current = null;
    },
  };
  const context = vm.createContext({
    window,
    document,
    localStorage,
    URL,
    URLSearchParams,
    Date,
    console,
  });
  vm.runInContext(attribution, context);
  vm.runInContext(script, context); // GSAP deliberately unavailable: controls must still work.
  return {
    selectors,
    buy,
    examples,
    videos,
    video,
    header,
    menu,
    toggle,
    documentEvents,
    animations,
  };
}

test('reduced motion suppresses entry, scroll and example transition animations', () => {
  const reduced = page({ reduced: true, withMotion: true });
  reduced.examples[1].click();
  assert.equal(reduced.animations.length, 0);
  assert.equal(reduced.selectors['#example-timestamp'].textContent, '08:58');
  const animated = page({ withMotion: true });
  assert.ok(animated.animations.length > 0);
});

test("checkout preserves the exact payment destination without attribution", () => {
  assert.equal(page().buy.href, checkout);
});
test("fresh, persisted, invalid, expired and blocked-storage affiliate cases", () => {
  assert.equal(
    new URL(page({ query: "?ref=QA_Valid" }).buy.href).searchParams.get(
      "client_reference_id",
    ),
    "qa_valid",
  );
  assert.equal(
    new URL(
      page({
        stored: JSON.stringify({
          code: "saved",
          expires_at: Date.now() + 100000,
        }),
      }).buy.href,
    ).searchParams.get("client_reference_id"),
    "saved",
  );
  assert.equal(page({ query: "?ref=%3Cbad%3E" }).buy.href, checkout);
  assert.equal(
    page({ stored: JSON.stringify({ code: "old", expires_at: 1 }) }).buy.href,
    checkout,
  );
  assert.equal(page({ stored: "legacy" }).buy.href, checkout);
  assert.equal(
    new URL(
      page({ query: "?ref=fresh", storageBlocked: true }).buy.href,
    ).searchParams.get("client_reference_id"),
    "fresh",
  );
});
test("each curated example updates the answer, selection and genuine timestamp link", () => {
  const p = page();
  for (const [i, seconds] of [8, 538, 1030].entries()) {
    p.examples[i].click();
    assert.equal(
      new URL(p.selectors["#example-source"].href).searchParams.get("t"),
      String(seconds),
    );
    assert.equal(p.examples[i].getAttribute("aria-pressed"), "true");
    assert.equal(
      p.examples.filter((e) => e.getAttribute("aria-pressed") === "true")
        .length,
      1,
    );
    assert.ok(p.selectors["#example-answer"].textContent.length > 40);
  }
});
test("demo switching updates both formats, poster, accessible label, fallback and download", () => {
  const p = page();
  p.videos[1].click();
  assert.equal(p.video.paused, true);
  assert.equal(p.video.loads, 1);
  assert.match(p.video.attrs.poster, /phone-poster.jpg$/);
  assert.match(p.video.attrs["aria-label"], /Telegram/);
  assert.match(p.video.children.source[0].src, /phone.webm$/);
  assert.match(p.video.children.source[1].src, /phone.mp4$/);
  assert.match(p.video.children.a.href, /phone.mp4$/);
  assert.match(p.selectors["#download-demo"].href, /phone.mp4$/);
  p.videos[0].click();
  assert.match(p.video.attrs.poster, /desktop-poster.jpg$/);
});
test("menu supports toggle, navigation close and Escape focus return", () => {
  const p = page();
  p.toggle.click();
  assert.equal(p.toggle.getAttribute("aria-expanded"), "true");
  assert.ok(p.menu.classes.has("is-open"));
  p.documentEvents.keydown({ key: "Escape" });
  assert.equal(p.toggle.getAttribute("aria-expanded"), "false");
  assert.equal(p.toggle.focused, true);
  p.toggle.click();
  p.menu.children.a[0].click();
  assert.equal(p.menu.classes.has("is-open"), false);
});
