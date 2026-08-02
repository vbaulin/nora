const mermaidBlocks = [...document.querySelectorAll("pre code.language-mermaid")];

if (mermaidBlocks.length > 0) {
  import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")
    .then(({ default: mermaid }) => {
      mermaidBlocks.forEach((code) => {
        const diagram = document.createElement("div");
        diagram.className = "mermaid";
        diagram.textContent = code.textContent;
        code.parentElement.replaceWith(diagram);
      });
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "neutral",
        flowchart: { htmlLabels: false, curve: "basis" },
      });
      return mermaid.run({ querySelector: ".mermaid" });
    })
    .catch(() => {
      // The original code blocks remain readable when the CDN is unavailable.
    });
}
