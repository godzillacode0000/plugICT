# PlugICT landing-page refresh

## Direction

Cloudflare-inspired information hierarchy and orange framed hero, adapted to PlugICT's existing identity. Calm Geist typography, off-white editorial sections, thin dividers, a real product demonstration and an honest one-time offer. This is not a Cloudflare clone; no Cloudflare branding or assets are included.

## Editing and preview

- `index.html`: semantic content, metadata, price and direct Stripe fallback.
- `assets/landing.css`: responsive design tokens and styles.
- `assets/landing.js`: menu, curated examples, video selection, checkout attribution and optional GSAP motion.
- `cloudflare/public-files.txt`: strict production file allowlist. Add any new public asset here.
- `npm run dev -- --host 0.0.0.0 --port 4173 --strictPort`: dependency-free local preview.
- Local-only `/__qa`: fixed-width iframe harness for responsive and no-JavaScript checks. It is never deployed.
- `npm test`: build boundary, existing Cloudflare tests and landing contracts.
- `npm run build:site`: generate the production `dist` artifact. Only the existing `main` deployment workflow publishes it.

## Content boundaries

The Silver Bullet walkthrough is explicitly curated, not live AI. Its paraphrases and timestamps (00:08, 08:58, 17:10) derive from the existing `assets/proof/answer-1.jpg`; video ID `tRq1hyGGtl4` is also present in the golden benchmark. The original screenshot and YouTube lesson remain directly accessible. Do not invent testimonials, urgency, search latency promises, trading outcomes or additional vault metrics.

The $18.99 lifetime offer, Stripe URL and 24-hour delivery policy are preserved. AI model costs are separate. Local vault search does not imply a chosen cloud AI provider receives no excerpts. The existing affiliate scripts and legal pages are unchanged. Do not submit a payment while testing.

## Motion and assets

- GSAP 3.15.0 and ScrollTrigger 3.15.0 are vendored unmodified from the official GitHub tag. Their copyright headers remain intact; see `assets/vendor/GSAP-LICENSE.txt` for the standard license reference.
- Motion: short staggered hero entry, restrained transform-only section entry and scroll-linked background drift. Native scrolling, no scroll lock, no perpetual animation. `gsap.matchMedia` respects reduced motion and reverts animations when preferences change.
- No CSS initially hides content. Missing GSAP cannot prevent reading, navigation, checkout or demo controls.
- Geist Latin variable font: `@fontsource-variable/geist` 5.3.0, SIL Open Font License, locally served. License bundled in `assets/fonts/OFL.txt`.
- Icons: original Lucide 0.577.0 SVG files, locally served with license in `assets/icons/LICENSE`. No custom inline SVG illustration.
- Hero: original AI-generated orange halftone artwork; 1536×1024 WebP, about 69 KB. Referenced Cloudflare for color/texture direction only.
- Videos, proof screenshot and PlugICT mark: existing repository assets. Video uses native controls, does not autoplay, and requests no video data before interaction (`preload="none"`). The text overview is an overview, not a verbatim transcript.

## Release

Review the branch/PR before merging. `main` triggers the existing GitHub Pages workflow. No backend, licensing, vault, affiliate service or legal-policy changes are needed for this refresh.
