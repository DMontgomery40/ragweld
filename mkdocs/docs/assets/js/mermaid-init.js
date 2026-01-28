window.addEventListener("load", () => {
  if (window.mermaid) {
    window.mermaid.initialize({
      startOnLoad: true,
      securityLevel: "strict",
      theme: "dark",
    });
    window.mermaid.run();
  }
});
