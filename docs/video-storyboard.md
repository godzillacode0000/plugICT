# PlugICT — Demo Video Plan (Kevin's vision, refined)

A landing-page video that shows **how PlugICT works** and delivers **the promise**
("stop scrubbing — find the exact lesson"). This captures Kevin's storyboard and
fine-tunes it for pacing, honesty, and buyer-expectation consistency.

The embed slot is already built (branch `hero-video-embed`) — drop the finished files in
`assets/video/`, set `window.PLUGICT.demoVideo`, and it appears. So this doc is about
**content**, not code.

---

## Kevin's original vision (as given)

1. **Result first** — ask the AI agent something → it answers based on PlugICT → the
   answer shows in Telegram (rich messages).
2. **Problem** — lots of screenshots of ICT's YouTube playlists / titles, to show the
   sheer volume of videos.
3. **Scale card** — a zoomed-in "bubble" card totaling the number of videos + total
   duration → "all ICT videos = more than XX,XXX hours" (duration TBC).
4. **2nd query** — a different question on screen; this time click the deep-link and land
   straight on the timestamped YouTube video.
5. **3rd query (fast)** — take a tip from a popular X account (e.g. ICT / ICT Ali Khan),
   drop the post text into the agent (via Telegram), get an answer.
6. **Delivery** — after purchase: fast Stripe checkout → payment confirmed → product
   delivered by email (link + `license.key` file).
7. **Setup** — animated recording of the buyer copying the link into their Hermes agent →
   Hermes desktop app configures itself → agent asks for the license key → drop the file.

---

## The main refinement: this is 3 videos, and the landing cut combines them into 55s

Kevin's full flow is ~2–4 minutes and install-heavy — too long for a landing *hook*.
Split the material into three videos, and make **one 55-second combined cut** for the
landing slot:

- **Video 1 — Landing cut (0:55):** result → scale → queries → fast buy/setup → offer.
  *This is the one embedded on the page.*
- **Video 2 — Buy & set up (2–4 min, separate):** the full purchase → delivery → Hermes
  config → license flow, for a "how it works / after you buy" section or the email.
- **Video 3 — Social/X clip (15–20s, 9:16):** the "tip from X → sourced answer" flow, for
  Telegram/X.

---

## Resolve BEFORE shooting (these can mislead buyers if left as-is)

1. **Pick ONE interface — Telegram or Hermes/Claude Desktop.** Kevin's hook shows the
   answer in *Telegram* but the setup beat configures the *Hermes desktop app*. A buyer
   must see the **same interface they'll actually get**, in every beat — or the demo sets a
   false expectation. **Decide this first; it changes every product-facing beat.**
2. **Real total-hours number.** "XX,XXX hours" must be computed from the 775-video vault.
   775 videos is confirmed; the hours figure is a placeholder until measured. Don't invent it.
3. **Redact the license key** (and buyer email / file paths) in the delivery beat. Never
   show a working key on screen.
4. **No real ICT / named-account tweets.** PlugICT's own footer states it is *not
   affiliated with ICT / Michael Huddleston*. Paraphrase as "a setup you saw on X" with
   generic text — showing a real named account's tweet implies endorsement.

---

## Video 1 — the 55-second landing cut (storyboard)

| Time | Beat | On screen (all PlugICT output must be REAL) | Source |
|---|---|---|---|
| **0:00–0:06** | **Result first** | A real question in your agent → a clean sourced answer: explanation + video title + exact timestamp. Lead with the payoff, not a logo. | Shoot real |
| **0:06–0:11** | **The pile** | Fast montage of ICT playlists — dozens of titles/thumbnails scrolling. *"The lesson is in there. Finding it is the hard part."* | Higgsfield OK |
| **0:11–0:15** | **Scale card** | One bold stat card, counts up: **775 videos · ~XX,XXX total hours** (real number TBC). | Higgsfield OK |
| **0:15–0:29** | **Query + deep-link (ANCHOR)** | A 2nd real query → click the returned link → it opens the **real YouTube video at the exact timestamp.** Question → answer → evidence → exact moment. Give this the most time. | Shoot real |
| **0:29–0:37** | **X-tip query (fast)** | Paraphrased "setup you saw on X" → drop into agent → sourced answer in seconds. Shows range. | Shoot real |
| **0:37–0:45** | **Buy + deliver** | One-click Stripe → "Payment confirmed" → email arrives with repo link + `license.key` (**key redacted**). | Shoot real |
| **0:45–0:50** | **Setup (fast, animated)** | Speed-ramp: paste install line → agent configures itself → drop in the license → first answer. No long terminal. | Higgsfield OK |
| **0:50–0:55** | **The offer** | *775 ICT videos. One searchable vault.* → *$18.99 one-time* → **Get PlugICT** (hold 2–3s). | Higgsfield OK |

**Golden rule:** 20% brand polish / 80% real product demo. The green anchor beat
(0:15–0:29) is the whole product — give it the most screen time.

---

## Voice-over (~50–55s, spoken calmly)

> ICT has already explained the concepts. The hard part is finding the exact lesson again.
>
> With PlugICT, you ask your AI agent a specific ICT question. PlugICT searches the local
> transcript vault and returns the most relevant evidence.
>
> You get the explanation, the original video title, and the exact timestamp — so you can
> verify the context yourself.
>
> It works through MCP-compatible AI agents and runs locally on your machine.
>
> Seven hundred and seventy-five ICT videos. One searchable vault.
>
> PlugICT. Stop scrubbing. Start finding.

**Positioning line to reinforce:** *"PlugICT doesn't replace the lessons — it helps you
find the right lesson when you need it."*

**Never say:** "never hallucinates", "guaranteed correct", "instant perfect answers",
"master ICT overnight", "replace studying."

---

## Who makes each beat

The rule that keeps this honest: **Higgsfield generates brand + motion; your screen
recorder captures anything shown as a real result.** Never let AI fabricate a query,
answer, timestamp, receipt, or license.

**Shoot real (screen recording):**
- Result answer (0:00–0:06)
- Deep-link opening the real video at the timestamp (0:15–0:29)
- X-tip query + sourced answer (0:29–0:37)
- Stripe receipt + delivery email, key redacted (0:37–0:45)

**Higgsfield can generate:**
- Playlist "pile" motion-collage (0:06–0:11)
- Scale-stat card count-up (0:11–0:15)
- Fast stylised setup montage (0:45–0:50)
- Brand outro / CTA lockup + transitions between beats (0:50–0:55)

---

## Captions & poster (for the embed)

- **Captions:** burn-in or a `.vtt` — assume many watch muted; every key message must read
  silently. Large text, one UI panel at a time, safe mobile margins (test ~390px).
- **Poster frame:** one real frame — the question + the cited result — with the honest
  overlay label *"See PlugICT find the exact lesson — ~50s"*.

---

## Embed status

`hero-video-embed` branch is built and verified. Video 1 → the main `.hero-video` slot
(`assets/video/*` + `window.PLUGICT.demoVideo`). Video 2 → a future "how it works / after
you buy" section or the fulfillment email. No further code needed for Video 1.

## Open for Kevin to decide
- **The interface** (Telegram vs Hermes) — decide first; it shapes every beat.
- The real total-hours figure.
- Keep Query #2 (X-tip) in the 55s cut, or drop to one killer query.
- Produce Video 2 / Video 3 now or after launch.
