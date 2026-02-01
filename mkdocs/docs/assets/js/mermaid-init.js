// Mermaid init for MkDocs Material.
//
// Why this exists:
// - MkDocs Material uses instant navigation (AJAX) so "DOMContentLoaded" only
//   fires once. We need to re-render diagrams on each page change.
// - Mermaid may load after DOMContentLoaded in some hosting scenarios; a single
//   one-shot check can silently skip rendering forever.
(function () {
  const MERMAID_INIT_FLAG = "__tribrid_mermaid_initialized__";
  const MERMAID_READY_POLL_MS = 50;
  const MERMAID_READY_TIMEOUT_MS = 8000;

  function normalizeMaterialGridCards() {
    // Material's card grid styling keys off the `.cards` class.
    // We avoid using the word "cards" in doc content, so we add it at runtime.
    const grids = Array.from(document.querySelectorAll(".md-typeset .grid.chunk_summaries, .md-typeset .grid.chunk_summary"));
    for (const grid of grids) {
      grid.classList.add("cards");
    }
  }

  function getMermaid() {
    // Mermaid attaches itself to window.
    return typeof window !== "undefined" ? window.mermaid : undefined;
  }

  function getMaterialColorScheme() {
    const scheme = document?.body?.getAttribute("data-md-color-scheme");
    return scheme || "default";
  }

  function getMermaidThemeForScheme(scheme) {
    return scheme === "slate" ? "dark" : "default";
  }

  function initMermaid(m) {
    const scheme = getMaterialColorScheme();
    const theme = getMermaidThemeForScheme(scheme);
    const prev = window[MERMAID_INIT_FLAG];
    if (prev && prev.theme === theme) return;

    m.initialize({
      // We explicitly render on navigation events.
      startOnLoad: false,
      securityLevel: "strict",
      theme,
      look: "handDrawn", // Mermaid v11: 3D sketchy style
      layout: "elk", // Mermaid v11: improved auto-layout
      flowchart: {
        useMaxWidth: true,
        htmlLabels: false,
        curve: "basis",
        padding: 20,
      },
      sequence: {
        useMaxWidth: true,
        wrap: true,
      },
      gantt: {
        useMaxWidth: true,
      },
    });

    window[MERMAID_INIT_FLAG] = { theme };
  }

  async function renderMermaid() {
    const m = getMermaid();
    if (!m) return false;

    normalizeMaterialGridCards();
    initMermaid(m);

    const nodes = Array.from(document.querySelectorAll(".mermaid"));
    if (nodes.length === 0) return true;

    try {
      // Mermaid v10/11: prefer run(); v9: fallback to init()
      if (typeof m.run === "function") {
        await m.run({ nodes });
      } else if (typeof m.init === "function") {
        m.init(undefined, nodes);
      }
    } catch (err) {
      // Keep docs usable even if a diagram has syntax errors.
      // eslint-disable-next-line no-console
      console.warn("Mermaid render failed", err);
    }

    return true;
  }

  function waitForMermaidAndRender() {
    const start = Date.now();

    const tick = () => {
      void renderMermaid().then((ok) => {
        if (ok) return;
        if (Date.now() - start >= MERMAID_READY_TIMEOUT_MS) return;
        setTimeout(tick, MERMAID_READY_POLL_MS);
      });
    };

    tick();
  }

  // Initial load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", waitForMermaidAndRender, { once: true });
  } else {
    waitForMermaidAndRender();
  }

  // Fallback (covers late-loaded scripts/resources)
  window.addEventListener("load", waitForMermaidAndRender, { once: true });

  // MkDocs Material instant navigation hook
  if (typeof document$ !== "undefined" && typeof document$.subscribe === "function") {
    document$.subscribe(() => {
      waitForMermaidAndRender();
    });
  }
})();
