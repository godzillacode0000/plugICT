# PlugICT landing-page design QA

final result: passed

Reviewed 2026-09-06 on branch `design/cloudflare-gsap-refresh`.

## Target and comparison

Cloudflare's captured homepage at 1348×926 informed the orange framed hero, restrained pill controls, generous spacing, sans-serif hierarchy and thin dividers. Reference and implementation screenshots were inspected together at the same desktop viewport. PlugICT deliberately retains its own mark, charcoal headline, accurate product copy, existing offer and product evidence. No Cloudflare branding or artwork is shipped.

Final screenshots:

- [Desktop hero](docs/qa/desktop-hero.jpg)
- [Desktop pricing](docs/qa/desktop-pricing.jpg)
- [Mobile hero](docs/qa/mobile-hero.jpg)

## Findings fixed

| Finding | Impact | Resolution |
| --- | --- | --- |
| Initial font asset unavailable | Wrong fallback typography | Vendored Geist Latin variable font; checked the final render with Geist loaded. |
| Header crowded at 320px | Logo and CTA collided | Reduced redundant header controls at narrow widths; kept the main hero purchase CTA and 44px menu target. |
| Pricing grid exceeded the narrow viewport | Horizontal scrolling | Removed intrinsic grid minimums and adjusted narrow price/headline sizes. Verified content width equals available width. |
| Interactive buttons appeared usable without scripts | Inactive controls | Disabled them in initial HTML, enabling them after enhancement. Native FAQ, video, navigation and direct checkout remain usable. |
| Existing affiliate test expected an empty endpoint | Test suite failed before redesign changes | Updated the contract to assert the already-configured public HTTPS endpoint; the production configuration itself is unchanged. |

## Visual and interaction review

- Desktop hero, evidence walkthrough, demo stage and pricing reviewed in the cloud browser. Spacing, typography, colors, image crop, borders and Lucide icon alignment checked. All sections retain coherent PlugICT content and working anchors.
- Responsive iframe checks at 320, 390, 768 and 1024 CSS-pixel frame widths. The browser's 15px scrollbar leaves 305, 375, 753 and 1009px content widths respectively; each matches its document scroll width. Desktop checked at 1348×926. This is responsive browser QA, not a claim of physical-device testing.
- Mobile menu opens and closes, Escape returns focus, and section links close the menu. Visible keyboard focus styles and semantic labels are present.
- Curated example selection updates the answer, pressed state and genuine YouTube timestamp. Browser checked the 08:58 destination; tests cover all three timestamps. Original proof image remains available.
- Desktop/Telegram selection updates media sources, poster, label, fallback and download link. Telegram video played through its 30.433-second duration with native controls. Videos do not autoplay on entry.
- JavaScript-disabled iframe: navigation remains visible, the direct Stripe link is intact, native FAQ expands, and the desktop video plus Telegram download fallback remain available.
- Reduced motion tested at the application boundary: no entry, scroll or example-transition animations are requested, while example selection still works. No native OS preference emulation was available in this browser.
- No application console errors observed. The browser's own extension emitted metadata errors unrelated to site code.
- Color contrast, focus, semantics, source links and no-JavaScript behavior manually reviewed. This is not an automated WCAG certification or a screen-reader audit.

## Automated checks

- `npm test`: 15 existing Cloudflare tests and 9 landing tests pass, plus the build-boundary script.
- `npm run build:site`: 55 allowlisted files copied successfully, with expected generated routes/headers/404. QA files, repository instructions, licenses for buyers and server scripts are not public build content.
- All local HTML/CSS assets, page routes, fragment links and ARIA references resolve. IDs are unique.
- Affiliate attribution: fresh, persisted, expired, invalid, legacy and blocked-storage cases preserve the exact payment destination and expected referral behavior. Tested locally without sending synthetic clicks to production analytics.
- Local HTTP verification: landing page 200, private repository paths 404, video byte range 206 with exact 1024-byte body, invalid range 416.
- Authored files pass `git diff --cached --check`. The two unmodified GSAP distribution files retain their upstream trailing whitespace; they are excluded from the authored-file whitespace check.

## Release boundary

The review branch does not deploy. Merge to `main` invokes the existing GitHub Pages workflow. No purchase was submitted; the existing Stripe destination and attribution were verified without making a transaction. Licensing, vault code, affiliate service/configuration and legal pages are unchanged. No remaining P0/P1/P2 findings from this scoped review.
