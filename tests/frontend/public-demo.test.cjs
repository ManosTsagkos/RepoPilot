const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { JSDOM } = require("jsdom");

const directory = path.resolve(__dirname, "../../docs");
const data = JSON.parse(readFileSync(path.join(directory, "demo-data.json"), "utf8"));
const adapter = readFileSync(path.join(directory, "assets/demo-api.js"), "utf8");

function demo(t, fetch) {
  const dom = new JSDOM(readFileSync(path.join(directory, "index.html"), "utf8"), {
    url: "https://manostsagkos.github.io/RepoPilot/",
    runScripts: "outside-only",
  });
  t.after(() => dom.window.close());
  const window = dom.window;
  window.structuredClone = structuredClone;
  window.fetch = fetch;
  window.eval(adapter);
  return window;
}

test("published dashboard boots below a repository path and exports a selected sample", async (t) => {
  const calls = [];
  const window = demo(t, async (url) => {
    calls.push(url);
    assert.equal(url, "./demo-data.json");
    return { ok: true, json: async () => structuredClone(data) };
  });
  const blobs = [];
  window.Blob = Blob;
  window.URL.createObjectURL = (blob) => { blobs.push(blob); return "blob:sample"; };
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () {};
  window.eval(readFileSync(path.join(directory, "assets/app.js"), "utf8"));
  const flush = () => new Promise((resolve) => setImmediate(resolve));
  await flush();
  await flush();
  const document = window.document;
  assert.equal(document.getElementById("live-mode").disabled, true);
  assert.equal(document.getElementById("github-status").textContent, "Sample issues");
  assert.equal(document.getElementById("analysis-result").hidden, false);
  assert.equal(document.querySelectorAll("[data-issue-number]").length, 5);
  const state = document.getElementById("issue-state");
  state.value = "all";
  document.getElementById("repository-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await flush();
  assert.equal(document.querySelectorAll("[data-issue-number]").length, 6);
  document.querySelector('[data-issue-number="235"]').click();
  document.getElementById("analyze-issue").click();
  await flush();
  const selected = data.samples.find((sample) => sample.issue.number === 235);
  assert.equal(document.getElementById("analysis-summary").textContent, selected.analysis.summary);
  document.getElementById("download-json").click();
  assert.deepEqual(JSON.parse(await blobs[0].text()), selected);
  assert.deepEqual(calls, ["./demo-data.json"]);
});

test("public demo returns independent samples and rejects live and unknown requests", async (t) => {
  const window = demo(t, async () => ({ ok: true, json: async () => structuredClone(data) }));
  const request = window.RepoPilotDemo.request;
  const options = { body: JSON.stringify({ mode: "demo", issue_number: 241 }) };
  const first = await request("/api/analyze", options);
  first.analysis.summary = "changed";
  assert.notEqual((await request("/api/analyze", options)).analysis.summary, "changed");
  await assert.rejects(request("/api/issues?mode=live"), /locally/);
  await assert.rejects(request("/api/analyze", { body: JSON.stringify({ mode: "live" }) }), /local app/);
  await assert.rejects(request("/api/analyze", { body: JSON.stringify({ mode: "demo", issue_number: 999 }) }), /dataset/);
  await assert.rejects(request("/api/unknown"), /not available/);
  await assert.rejects(request("/api/config", { signal: { aborted: true } }), { name: "AbortError" });
});

test("demo data loading can recover after a failed response", async (t) => {
  let attempts = 0;
  const window = demo(t, async () => ({ ok: ++attempts > 1, json: async () => structuredClone(data) }));
  await assert.rejects(window.RepoPilotDemo.request("/api/config"), /load the demo data/);
  assert.equal((await window.RepoPilotDemo.request("/api/config")).llm_configured, false);
  assert.equal(attempts, 2);
});
