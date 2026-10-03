(() => {
  "use strict";

  // GitHub Pages serves the same dashboard with public fixtures instead of a backend.
  let dataset;
  async function samples() {
    if (!dataset) {
      dataset = fetch("./demo-data.json").then((response) => {
        if (!response.ok) throw new Error("Couldn’t load the demo data. Reload to try again.");
        return response.json();
      }).catch((error) => { dataset = null; throw error; });
    }
    return dataset;
  }

  window.RepoPilotDemo = {
    async request(url, options = {}) {
      const data = await samples();
      if (options.signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
      const endpoint = new URL(url, "https://demo.local");
      if (endpoint.pathname === "/api/config") return structuredClone(data.config);
      if (endpoint.pathname === "/api/issues") {
        if (endpoint.searchParams.get("mode") !== "demo") {
          throw new Error("Run RepoPilot locally to connect a real GitHub repository.");
        }
        const state = endpoint.searchParams.get("state") || "open";
        const limit = Number(endpoint.searchParams.get("limit") || 30);
        return {
          repository: data.config.demo_repository,
          mode: "demo",
          issues: structuredClone(data.samples.map((sample) => sample.issue)
            .filter((issue) => state === "all" || issue.state === state).slice(0, limit)),
          notice: "Interactive demo with sample issues and pre-written analyses. No GitHub or LLM requests.",
        };
      }
      if (endpoint.pathname === "/api/analyze") {
        const body = JSON.parse(options.body);
        if (body.mode !== "demo") throw new Error("Live analysis is available in the local app.");
        const sample = data.samples.find((item) => item.issue.number === body.issue_number);
        if (!sample) throw new Error("This issue is not in the demo dataset.");
        return structuredClone(sample);
      }
      throw new Error("This action is not available in the public demo.");
    },
  };
})();
