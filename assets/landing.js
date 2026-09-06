/* Progressive enhancement: content, FAQs, video and checkout work without GSAP. */
(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  $$('[data-example], [data-video]').forEach((button) => { button.disabled = false; });

  $$("[data-year]").forEach((element) => {
    element.textContent = new Date().getFullYear();
  });
  $$("[data-buy-link]").forEach((link) => {
    if (typeof window.plugictStripeUrl === "function") {
      link.href = window.plugictStripeUrl(link.href);
    }
  });

  const header = $(".site-header");
  const menu = $(".site-nav");
  const menuButton = $(".menu-toggle");
  const menuIcon = menuButton.querySelector("img");
  header.classList.add("nav-enhanced");
  menuButton.hidden = false;
  function closeMenu(returnFocus = false) {
    menu.classList.remove("is-open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", "Open navigation");
    menuIcon.src = "assets/icons/menu.svg";
    if (returnFocus) menuButton.focus();
  }
  menuButton.addEventListener("click", () => {
    const opening = menuButton.getAttribute("aria-expanded") !== "true";
    menu.classList.toggle("is-open", opening);
    menuButton.setAttribute("aria-expanded", String(opening));
    menuButton.setAttribute(
      "aria-label",
      opening ? "Close navigation" : "Open navigation",
    );
    menuIcon.src = opening ? "assets/icons/x.svg" : "assets/icons/menu.svg";
  });
  menu
    .querySelectorAll("a")
    .forEach((link) => link.addEventListener("click", () => closeMenu()));
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      menuButton.getAttribute("aria-expanded") === "true"
    )
      closeMenu(true);
  });
  document.addEventListener("click", (event) => {
    if (!header.contains(event.target)) closeMenu();
  });
  window
    .matchMedia("(min-width: 801px)")
    .addEventListener("change", () => closeMenu());
  const updateHeader = () =>
    header.classList.toggle("is-scrolled", window.scrollY > 15);
  window.addEventListener("scroll", updateHeader, { passive: true });
  updateHeader();

  // Paraphrases and timestamps trace to assets/proof/answer-1.jpg.
  // This is a labelled, curated walkthrough, never a simulated live search.
  const examples = {
    definition: {
      question: "What is ICT’s Silver Bullet model?",
      title: "A time-based trading model.",
      answer:
        "ICT introduces the Silver Bullet as a time-based model. Start with his definition, then watch the surrounding lesson for the full context.",
      timestamp: "00:08",
      seconds: 8,
    },
    time: {
      question: "Which time zone does ICT use?",
      title: "Start with New York local time.",
      answer:
        "ICT explains that the times he refers to are based on New York local time. Watch the original passage before applying that context to your study.",
      timestamp: "08:58",
      seconds: 538,
    },
    source: {
      question: "Where does ICT explain the rules?",
      title: "Return to the explanation.",
      answer:
        "Later in the lesson, ICT returns to the model’s rule-based use of time and price. Follow the timestamp and hear the explanation in context.",
      timestamp: "17:10",
      seconds: 1030,
    },
  };
  $$("[data-example]").forEach((button) =>
    button.addEventListener("click", () => {
      const example = examples[button.dataset.example];
      if (!example) return;
      $$("[data-example]").forEach((tab) => {
        const active = tab === button;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-pressed", String(active));
      });
      $("#example-question").textContent = example.question;
      $("#example-title").textContent = example.title;
      $("#example-answer").textContent = example.answer;
      $("#example-timestamp").textContent = example.timestamp;
      $("#example-source").href =
        `https://www.youtube.com/watch?v=tRq1hyGGtl4&t=${example.seconds}`;
      if (window.gsap && !motion.matches) {
        window.gsap.fromTo(
          "#example-content",
          { opacity: 0.5, y: 5 },
          {
            opacity: 1,
            y: 0,
            duration: 0.28,
            overwrite: true,
            clearProps: "opacity,transform",
          },
        );
      }
    }),
  );

  const video = $("#product-video");
  const videos = {
    desktop: {
      name: "desktop",
      label: "PlugICT desktop workflow demonstration",
      caption:
        "Search the local vault through a terminal-capable AI agent. Follow the returned citations to the original teaching.",
    },
    phone: {
      name: "phone",
      label: "PlugICT Telegram workflow demonstration",
      caption:
        "A connected agent brings the conversation to Telegram. This requires an agent integration; PlugICT itself is the local knowledge vault.",
    },
  };
  $$("[data-video]").forEach((button) =>
    button.addEventListener("click", () => {
      if (button.getAttribute("aria-pressed") === "true") return;
      const selected = videos[button.dataset.video];
      if (!selected) return;
      video.pause();
      video.setAttribute(
        "poster",
        `assets/video/plugict-demo-${selected.name}-poster.jpg`,
      );
      video.setAttribute("aria-label", selected.label);
      video.querySelectorAll("source").forEach((source) => {
        const extension = source.type === "video/webm" ? "webm" : "mp4";
        source.src = `assets/video/plugict-demo-${selected.name}.${extension}`;
      });
      video.querySelector("a").href =
        `assets/video/plugict-demo-${selected.name}.mp4`;
      video.querySelector("a").textContent =
        `Download the ${selected.name === "phone" ? "Telegram" : "desktop"} demo`;
      video.load();
      $("#demo-caption").textContent = selected.caption;
      $("#download-demo").href =
        `assets/video/plugict-demo-${selected.name}.mp4`;
      $$("[data-video]").forEach((tab) => {
        tab.classList.toggle("is-active", tab === button);
        tab.setAttribute("aria-pressed", String(tab === button));
      });
    }),
  );
  // Do not play a hidden/offscreen demo, and never start media automatically.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) video.pause();
  });
  if ("IntersectionObserver" in window) {
    const visibility = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) video.pause();
      },
      { threshold: 0.05 },
    );
    visibility.observe(video);
  }

  // No CSS hides content. If either optional motion asset fails, the page stays usable.
  if (!window.gsap || !window.ScrollTrigger) return;
  const { gsap, ScrollTrigger } = window;
  gsap.registerPlugin(ScrollTrigger);
  const media = gsap.matchMedia();
  media.add("(prefers-reduced-motion: no-preference)", () => {
    gsap.from("[data-hero]", {
      y: 18,
      opacity: 0,
      duration: 0.8,
      stagger: 0.07,
      ease: "power2.out",
      clearProps: "opacity,transform",
    });
    // Transform-only, scroll-linked background drift; native scrolling is preserved.
    gsap.to(".hero-art", {
      yPercent: 7,
      scale: 1.06,
      ease: "none",
      scrollTrigger: {
        trigger: ".hero",
        start: "top top",
        end: "bottom top",
        scrub: 0.7,
      },
    });
    $$("[data-reveal]").forEach((element) => {
      gsap.from(element, {
        y: 20,
        duration: 0.7,
        ease: "power2.out",
        clearProps: "transform",
        scrollTrigger: { trigger: element, start: "top 94%", once: true },
      });
    });
  });
  document.fonts?.ready.then(() => ScrollTrigger.refresh());
  window.addEventListener("load", () => ScrollTrigger.refresh(), {
    once: true,
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) ScrollTrigger.refresh();
  });
})();
