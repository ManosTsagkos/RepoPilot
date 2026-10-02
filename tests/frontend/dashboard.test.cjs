const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { JSDOM, VirtualConsole } = require("jsdom");

const staticDirectory = path.resolve(__dirname, "../../src/repopilot/static");
const html = readFileSync(path.join(staticDirectory, "index.html"), "utf8");
const script = readFileSync(path.join(staticDirectory, "app.js"), "utf8");
const demoRepository = "repopilot/taskboard";

function issue(number, overrides = {}) {
  return {
    number,
    title: number === 101 ? "Export stops on Unicode text" : "Add a task shortcut",
    body: number === 101 ? "Export fails with an emoji. Browser: Firefox." : "Press N to create a task.",
    state: "open",
    labels: [number === 101 ? "bug" : "enhancement"],
    author: "tester",
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-25T12:00:00Z",
    comments: 2,
    html_url: `https://github.com/octo/project/issues/${number}`,
    body_truncated: false,
    ...overrides,
  };
}

function result(selected, mode = "demo", repository = demoRepository, overrides = {}) {
  return {
    repository,
    mode,
    issue: selected,
    analysis: {
      summary: `Summary of issue ${selected.number}`,
      category: selected.number === 101 ? "bug" : "feature",
      priority: selected.number === 101 ? "high" : "low",
      rationale: "Based on the reported impact.",
      suggested_labels: ["needs-triage"],
      missing_info: ["Application version."],
      next_steps: ["Reproduce the reported behavior."],
      draft_reply: `Reply for issue ${selected.number}.`,
    },
    provider: mode === "demo" ? "demo" : "openai",
    model: mode === "demo" ? null : "test-model",
    cached: false,
    ...overrides,
  };
}

function dashboard(t) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(error));
  const dom = new JSDOM(html, {
    url: "http://127.0.0.1:8000/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole,
  });
  const { window } = dom;
  const requests = [];
  const downloads = [];
  const clipboard = [];
  const clipboardTimers = [];
  const intervals = [];
  const clock = { now: Date.now() };
  window.Date.now = () => clock.now;
  window.setInterval = (callback) => { intervals.push(callback); return intervals.length; };
  const setTimeout = window.setTimeout.bind(window);
  const clearTimeout = window.clearTimeout.bind(window);
  window.setTimeout = (callback, delay, ...args) => {
    if (delay === 2000) {
      const timer = { callback, active: true };
      clipboardTimers.push(timer);
      return timer;
    }
    return setTimeout(callback, delay, ...args);
  };
  window.clearTimeout = (timer) => {
    if (timer && typeof timer === "object" && "active" in timer) timer.active = false;
    else clearTimeout(timer);
  };
  window.fetch = (url, options = {}) => new Promise((resolve, reject) => {
    requests.push({ url, options, resolve, reject, settled: false });
  });
  window.Blob = Blob;
  window.URL.createObjectURL = (blob) => { downloads.push({ blob }); return "blob:repopilot-test"; };
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () {
    if (this.download) downloads.at(-1).filename = this.download;
  };
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText: async (text) => { clipboard.push(text); } },
  });
  window.addEventListener("error", (event) => errors.push(event.error));
  window.eval(script);
  t.after(() => {
    window.close();
    assert.deepEqual(errors, [], "the dashboard should not throw uncaught errors");
  });
  const $ = (id) => window.document.getElementById(id);
  const pending = (pathname) => requests.find((request) => !request.settled && !request.options.signal?.aborted && new URL(request.url, window.location.href).pathname === pathname);
  const respond = (request, data, status = 200) => {
    assert.ok(request, "expected a pending API request");
    request.settled = true;
    request.resolve({ ok: status >= 200 && status < 300, status, json: async () => data });
  };
  const flush = async () => { for (let i = 0; i < 3; i++) await new Promise(setImmediate); };
  const submit = () => $("repository-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  const filter = (id, value, event = "change") => {
    $(id).value = value;
    $(id).dispatchEvent(new window.Event(event, { bubbles: true }));
  };
  const select = (number) => window.document.querySelector(`[data-issue-number="${number}"]`).click();
  return { window, $, requests, downloads, clipboard, clipboardTimers, intervals, clock, pending, respond, flush, submit, filter, select };
}

function configured(overrides = {}) {
  return { github_configured: false, llm_configured: true, model: "test-model", demo_repository: demoRepository, version: "0.1.0", ...overrides };
}

async function boot(h, { issues = [issue(101), issue(102)], config = configured(), analysis = null } = {}) {
  h.respond(h.pending("/api/config"), config);
  h.respond(h.pending("/api/issues"), { repository: demoRepository, mode: "demo", issues, notice: "Sample issues and pre-written analyses." });
  await h.flush();
  if (issues.length) {
    h.respond(h.pending("/api/analyze"), analysis || result(issues[0]));
    await h.flush();
  }
}

async function live(h, issues = [issue(101), issue(102)], repository = "octo/project") {
  h.$("live-mode").click();
  h.$("repository").value = repository;
  h.submit();
  h.respond(h.pending("/api/issues"), { repository: "octo/project", mode: "live", issues, notice: "Latest GitHub issues." });
  await h.flush();
}

async function analyzeLive(h, selected = issue(101), overrides = {}) {
  h.$("analyze-issue").click();
  h.respond(h.pending("/api/analyze"), result(selected, "live", "octo/project", overrides));
  await h.flush();
}

test("demo boots without API keys and labels sample analysis clearly", async (t) => {
  const h = dashboard(t);
  await boot(h, { config: configured({ llm_configured: false }) });
  assert.equal(h.$("issue-count").textContent, "2");
  assert.equal(h.$("analysis-count").textContent, "1");
  assert.equal(h.$("priority-count").textContent, "1");
  assert.equal(h.$("detail-number").textContent, "ISSUE #101");
  assert.match(h.$("analysis-provenance").textContent, /Pre-written sample/);
  assert.equal(h.$("analysis-result").hidden, false);
  assert.equal(h.$("github-link").hidden, true);
  assert.equal(h.$("demo-mode").getAttribute("aria-pressed"), "true");
  assert.ok(h.requests.every((request) => request.url.startsWith("/api/")));
});

test("issue and LLM content are rendered as text, including reply drafts", async (t) => {
  const h = dashboard(t);
  const payload = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>';
  const selected = issue(101, { title: payload, body: payload, labels: [payload], author: payload });
  const sample = result(selected);
  sample.analysis.summary = payload;
  sample.analysis.draft_reply = payload;
  sample.analysis.suggested_labels = [payload];
  await boot(h, { issues: [selected], analysis: sample });
  assert.equal(h.$("detail-title").textContent, payload);
  assert.equal(h.$("issue-body").textContent, payload);
  assert.equal(h.$("analysis-summary").textContent, payload);
  assert.equal(h.$("draft-reply").textContent, payload);
  assert.equal(h.$("issue-detail").querySelector("img, script"), null);
  assert.equal(h.window.injected, undefined);
});

test("switching the selected issue cancels analysis and ignores a late result", async (t) => {
  const h = dashboard(t);
  h.respond(h.pending("/api/config"), configured());
  h.respond(h.pending("/api/issues"), { repository: demoRepository, mode: "demo", issues: [issue(101), issue(102)] });
  await h.flush();
  const oldRequest = h.pending("/api/analyze");
  h.select(102);
  assert.equal(oldRequest.options.signal.aborted, true);
  h.respond(oldRequest, result(issue(101)));
  await h.flush();
  assert.equal(h.$("detail-number").textContent, "ISSUE #102");
  assert.equal(h.$("analysis-result").hidden, true);
  assert.equal(h.$("analyze-issue").disabled, false);
  h.$("analyze-issue").click();
  h.respond(h.pending("/api/analyze"), result(issue(102)));
  await h.flush();
  assert.equal(h.$("analysis-summary").textContent, "Summary of issue 102");
  assert.equal(h.$("analysis-count").textContent, "1");
});

test("an old repository request cannot replace a newer mode or clear its loading state", async (t) => {
  const h = dashboard(t);
  await boot(h);
  h.$("live-mode").click();
  h.$("repository").value = "octo/project";
  h.submit();
  const oldRequest = h.pending("/api/issues");
  h.$("demo-mode").click();
  const newRequest = h.pending("/api/issues");
  assert.equal(oldRequest.options.signal.aborted, true);
  h.respond(oldRequest, { repository: "octo/project", mode: "live", issues: [issue(900)] });
  await h.flush();
  assert.equal(h.$("load-issues").disabled, true);
  assert.equal(h.$("repository").value, demoRepository);
  h.respond(newRequest, { repository: demoRepository, mode: "demo", issues: [issue(101)] });
  await h.flush();
  assert.equal(h.$("detail-number").textContent, "ISSUE #101");
  assert.equal(h.$("load-issues").disabled, false);
});

test("live analysis waits for configuration and a failed check can be retried", async (t) => {
  const h = dashboard(t);
  const configRequest = h.pending("/api/config");
  h.respond(h.pending("/api/issues"), { repository: demoRepository, mode: "demo", issues: [] });
  await h.flush();
  await live(h);
  assert.equal(h.$("analyze-issue").disabled, true);
  assert.match(h.$("config-notice-message").textContent, /Checking/);
  h.respond(configRequest, { error: { message: "Temporarily unavailable" } }, 503);
  await h.flush();
  assert.equal(h.$("retry-config").hidden, false);
  assert.equal(h.$("analyze-issue").disabled, true);
  h.$("retry-config").click();
  assert.equal(h.$("retry-config").disabled, true);
  h.respond(h.pending("/api/config"), configured());
  await h.flush();
  assert.equal(h.$("analyze-issue").disabled, false);
  assert.equal(h.$("config-notice").hidden, true);
});

test("missing LLM key still permits live issue loading with a visible setup message", async (t) => {
  const h = dashboard(t);
  await boot(h, { config: configured({ llm_configured: false }) });
  await live(h);
  assert.equal(h.$("issue-count").textContent, "2");
  assert.equal(h.$("analyze-issue").disabled, true);
  assert.match(h.$("config-notice-message").textContent, /OPENAI_API_KEY/);
  assert.match(h.$("analysis-provenance").textContent, /restart/);
  assert.equal(h.pending("/api/analyze"), undefined);
});

test("search, analyzed filters, and reset behave consistently", async (t) => {
  const h = dashboard(t);
  await boot(h);
  h.filter("issue-search", "#102", "input");
  assert.equal(h.$("visible-count").textContent, "1");
  assert.equal(h.$("issue-list").querySelector("button").dataset.issueNumber, "102");
  h.filter("issue-search", "Firefox", "input");
  assert.equal(h.$("issue-list").querySelector("button").dataset.issueNumber, "101");
  h.filter("issue-search", "", "input");
  h.filter("category-filter", "feature");
  assert.equal(h.$("visible-count").textContent, "0");
  assert.equal(h.$("filter-note").hidden, false);
  h.$("issue-list").querySelector("button").click();
  assert.equal(h.$("visible-count").textContent, "2");
  assert.equal(h.$("category-filter").value, "all");
  assert.equal(h.window.document.activeElement, h.$("issue-search"));
  h.filter("priority-filter", "high");
  assert.equal(h.$("visible-count").textContent, "1");
});

test("reload clears filters and old live analysis when issue content changes", async (t) => {
  const h = dashboard(t);
  await boot(h);
  await live(h);
  await analyzeLive(h);
  h.filter("issue-search", "Export", "input");
  h.filter("category-filter", "bug");
  h.filter("priority-filter", "high");
  h.$("issue-state").value = "closed";
  h.submit();
  const request = h.pending("/api/issues");
  assert.equal(new URL(request.url, h.window.location.href).searchParams.get("state"), "closed");
  h.respond(request, { repository: "octo/project", mode: "live", issues: [issue(101, { title: "Resolved export problem", body: "Updated report", state: "closed" })] });
  await h.flush();
  assert.equal(h.$("issue-search").value, "");
  assert.equal(h.$("category-filter").value, "all");
  assert.equal(h.$("priority-filter").value, "all");
  assert.equal(h.$("visible-count").textContent, "1");
  assert.equal(h.$("analysis-count").textContent, "0");
  assert.equal(h.$("analysis-result").hidden, true);
  assert.equal(h.$("issue-body").textContent, "Updated report");
  assert.equal(h.$("detail-state").textContent, "closed");
});

test("analysis updates the original report and JSON export matches the selected result", async (t) => {
  const h = dashboard(t);
  await boot(h);
  await live(h);
  h.window.document.querySelector(".original-report").open = true;
  const updated = issue(101, { title: "Updated export title", body: "Fresh body returned with analysis", body_truncated: true });
  await analyzeLive(h, updated);
  assert.equal(h.$("detail-title").textContent, updated.title);
  assert.equal(h.$("issue-body").textContent, updated.body);
  assert.equal(h.$("truncated-notice").hidden, false);
  assert.equal(h.window.document.querySelector(".original-report").open, true);
  h.$("download-json").click();
  const exported = JSON.parse(await h.downloads[0].blob.text());
  assert.equal(exported.issue.body, updated.body);
  assert.equal(exported.analysis.draft_reply, "Reply for issue 101.");
  assert.equal(h.downloads[0].filename, "repopilot-octo-project-issue-101.json");
  h.select(102);
  h.$("download-json").click();
  assert.equal(h.downloads.length, 1, "a hidden previous result cannot be exported for another issue");
});

test("mismatched analysis identity is rejected and does not replace the issue", async (t) => {
  const h = dashboard(t);
  await boot(h);
  await live(h);
  h.$("analyze-issue").click();
  h.respond(h.pending("/api/analyze"), result(issue(102), "live", "octo/project"));
  await h.flush();
  assert.equal(h.$("analysis-error").hidden, false);
  assert.match(h.$("analysis-error-message").textContent, /did not match/);
  assert.equal(h.$("detail-number").textContent, "ISSUE #101");
  assert.equal(h.$("analysis-count").textContent, "0");
});

test("live session results expire and cannot be copied or exported indefinitely", async (t) => {
  const h = dashboard(t);
  await boot(h);
  await live(h);
  await analyzeLive(h);
  h.clock.now += 5 * 60 * 1000 + 1;
  h.intervals[0]();
  assert.equal(h.$("analysis-result").hidden, true);
  assert.equal(h.$("analysis-count").textContent, "0");
  assert.equal(h.$("priority-count").textContent, "0");
  h.$("download-json").click();
  h.$("copy-reply").click();
  await h.flush();
  assert.equal(h.downloads.length, 0);
  assert.equal(h.clipboard.length, 0);
  h.$("analyze-issue").click();
  assert.ok(h.pending("/api/analyze"));
});

test("clipboard success copies the current draft and failure selects it for manual copy", async (t) => {
  const h = dashboard(t);
  await boot(h);
  h.$("copy-reply").click();
  await h.flush();
  assert.deepEqual(h.clipboard, ["Reply for issue 101."]);
  assert.equal(h.clipboardTimers[0].active, false, "successful clipboard writes clear their timeout");
  Object.defineProperty(h.window.navigator, "clipboard", { value: undefined, configurable: true });
  h.$("copy-reply").click();
  await h.flush();
  assert.equal(h.window.getSelection().toString(), "Reply for issue 101.");
  assert.match(h.$("toast").textContent, /Ctrl\+C/);
});

test("a delayed clipboard rejection never selects another issue's draft", async (t) => {
  const h = dashboard(t);
  await boot(h);
  let rejectCopy;
  h.window.navigator.clipboard.writeText = () => new Promise((resolve, reject) => { rejectCopy = reject; });
  h.$("copy-reply").click();
  h.select(102);
  rejectCopy(new Error("Clipboard denied"));
  await h.flush();
  assert.equal(h.window.getSelection().toString(), "");
  assert.match(h.$("toast").textContent, /selected issue changed/);
});

test("a clipboard request that never settles falls back without duplicate late feedback", async (t) => {
  const h = dashboard(t);
  await boot(h);
  let finishCopy;
  h.window.navigator.clipboard.writeText = () => new Promise((resolve) => { finishCopy = resolve; });
  h.$("copy-reply").click();
  assert.equal(h.clipboardTimers.length, 1);
  h.clipboardTimers[0].callback();
  await h.flush();
  assert.equal(h.window.getSelection().toString(), "Reply for issue 101.");
  assert.match(h.$("toast").textContent, /Ctrl\+C/);
  assert.equal(h.clipboardTimers[0].active, false);
  finishCopy();
  await h.flush();
  assert.match(h.$("toast").textContent, /Ctrl\+C/, "late clipboard settlement must not replace fallback feedback");
});

test("API failures show actionable messages and retries restore the workspace", async (t) => {
  const h = dashboard(t);
  await boot(h);
  h.submit();
  h.respond(h.pending("/api/issues"), { error: { message: "GitHub rate limit reached.", retry_after: 20 } }, 429);
  await h.flush();
  assert.equal(h.$("workspace-error").hidden, false);
  assert.match(h.$("workspace-error-message").textContent, /20 seconds/);
  assert.equal(h.$("load-issues").disabled, false);
  h.$("retry-issues").click();
  h.respond(h.pending("/api/issues"), { repository: demoRepository, mode: "demo", issues: [] });
  await h.flush();
  assert.equal(h.$("workspace-error").hidden, true);
  assert.equal(h.$("issue-count").textContent, "0");
  assert.equal(h.$("detail-empty").hidden, false);
});

test("non-JSON and invalid issue-list responses fail without a stuck loading state", async (t) => {
  const h = dashboard(t);
  await boot(h);
  h.submit();
  const request = h.pending("/api/issues");
  request.settled = true;
  request.resolve({ ok: true, status: 200, json: async () => { throw new Error("Invalid JSON"); } });
  await h.flush();
  assert.match(h.$("workspace-error-message").textContent, /unexpected response/);
  assert.equal(h.$("load-issues").disabled, false);
  h.$("retry-issues").click();
  h.respond(h.pending("/api/issues"), { repository: "octo/project", issues: null });
  await h.flush();
  assert.match(h.$("workspace-error-message").textContent, /invalid issue list/);
  assert.equal(h.$("issue-list").getAttribute("aria-busy"), "false");
});

test("repository URLs normalize and invalid hosts, auth, query, or paths never fetch", async (t) => {
  const h = dashboard(t);
  await boot(h);
  await live(h, [issue(101)], "https://github.com/octo/project.git/");
  const liveRequest = h.requests.find((request) => request.url.includes("mode=live"));
  assert.equal(new URL(liveRequest.url, h.window.location.href).searchParams.get("repository"), "octo/project");
  assert.equal(h.$("repository").value, "octo/project");
  const count = h.requests.length;
  for (const input of [
    "https://evil.test/octo/project", "https://token@github.com/octo/project",
    "https://github.com/octo/project?x=1", "https://github.com/octo/project#readme",
    "https://github.com/octo/project/issues", "https://[bad/octo/project", "octo/..",
  ]) {
    h.$("repository").value = input;
    h.submit();
    assert.equal(h.$("workspace-error").hidden, false, input);
  }
  assert.equal(h.requests.length, count);
});

test("issue selection keeps keyboard focus and live links allow only HTTPS GitHub", async (t) => {
  const h = dashboard(t);
  await boot(h);
  const button = h.$("issue-list").querySelector('[data-issue-number="102"]');
  button.focus();
  button.click();
  assert.equal(h.window.document.activeElement.dataset.issueNumber, "102");
  assert.equal(h.window.document.activeElement.getAttribute("aria-controls"), "issue-detail");
  assert.equal(h.window.document.activeElement.getAttribute("aria-pressed"), "true");
  await live(h, [issue(101, { html_url: "javascript:alert(1)" }), issue(102)]);
  assert.equal(h.$("github-link").hidden, true);
  assert.equal(h.$("github-link").hasAttribute("href"), false);
  h.select(102);
  assert.equal(h.$("github-link").hidden, false);
  assert.equal(h.$("github-link").href, "https://github.com/octo/project/issues/102");
  h.$("analyze-issue").click();
  assert.equal(h.$("issue-detail").getAttribute("aria-busy"), "true");
  assert.equal(h.$("analyze-issue").getAttribute("aria-busy"), "true");
});

test("a late config response does not erase an analysis error", async (t) => {
  const h = dashboard(t);
  const configRequest = h.pending("/api/config");
  h.respond(h.pending("/api/issues"), { repository: demoRepository, mode: "demo", issues: [issue(101)] });
  await h.flush();
  h.respond(h.pending("/api/analyze"), { error: { message: "Sample temporarily unavailable." } }, 503);
  await h.flush();
  h.respond(configRequest, configured());
  await h.flush();
  assert.equal(h.$("analysis-error").hidden, false);
  assert.match(h.$("analysis-error-message").textContent, /Sample temporarily unavailable/);
});
