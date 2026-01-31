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

  function getMermaid() {
    // Mermaid attaches itself to window.
    return typeof window !== "undefined" ? window.mermaid : undefined;
  }

  function initMermaidOnce(m) {
    if (window[MERMAID_INIT_FLAG]) return;

    m.initialize({
      // We explicitly render on navigation events.
      startOnLoad: false,
      theme: "dark",
      look: "handDrawn", // Mermaid v11: 3D sketchy style
      layout: "elk", // Mermaid v11: improved auto-layout
      flowchart: {
        useMaxWidth: true,
        htmlLabels: true,
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

    window[MERMAID_INIT_FLAG] = true;
  }

  async function renderMermaid() {
    const m = getMermaid();
    if (!m) return false;

    initMermaidOnce(m);

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
