(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const ANALYSIS_TTL = 5 * 60 * 1000;
  const MAX_SAVED_ANALYSES = 100;
  const state = {
    mode: "demo",
    repository: "repopilot/taskboard",
    liveRepository: "",
    config: null,
    configStatus: "loading",
    issues: [],
    selectedNumber: null,
    analyses: new Map(),
    loadingIssues: false,
    loadingAnalysis: false,
  };
  let issueRequest = null;
  let analysisRequest = null;
  let toastTimer = null;

  const categoryNames = {
    bug: "Bug",
    feature: "Feature",
    question: "Question",
    documentation: "Documentation",
    maintenance: "Maintenance",
  };

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = String(content);
    return node;
  }

  function announce(message) {
    $("status-message").textContent = message;
  }

  function toast(message) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").hidden = false;
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3500);
  }

  function analysisKey(number) {
    return `${state.mode}:${state.repository.toLowerCase()}:${number}`;
  }

  function selectedIssue() {
    return state.issues.find((issue) => issue.number === state.selectedNumber);
  }

  function selectedAnalysis() {
    return analysisForIssue(state.selectedNumber);
  }

  function analysisForIssue(number) {
    const key = analysisKey(number);
    const saved = state.analyses.get(key);
    if (!saved) return undefined;
    if (saved.expiresAt <= Date.now()) return undefined;
    return saved.result;
  }

  function saveAnalysis(key, result) {
    state.analyses.delete(key);
    state.analyses.set(key, { result, expiresAt: result.mode === "demo" ? Infinity : Date.now() + ANALYSIS_TTL });
    while (state.analyses.size > MAX_SAVED_ANALYSES) state.analyses.delete(state.analyses.keys().next().value);
  }

  function expireAnalyses() {
    let changed = false;
    for (const [key, saved] of state.analyses) {
      if (saved.expiresAt <= Date.now()) {
        state.analyses.delete(key);
        changed = true;
      }
    }
    if (changed) {
      renderIssues();
      renderDetails();
      renderStats();
    }
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Unknown date";
    return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(date);
  }

  async function request(url, options = {}) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("Couldn’t reach the server. Check that RepoPilot is running and try again.");
    }

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned an unexpected response. Try again or check the server logs.");
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("The server returned an unexpected response. Try again or check the server logs.");
    }
    if (!response.ok) {
      const retryAfter = data.error?.retry_after;
      const wait = Number.isFinite(retryAfter) && retryAfter > 0 ? ` Try again in ${retryAfter} seconds.` : "";
      throw new Error((data.error?.message || `Request failed (${response.status}).`) + wait);
    }
    return data;
  }

  async function loadConfig() {
    state.configStatus = "loading";
    $("retry-config").disabled = true;
    renderConnectionNotice();
    updateAnalyzeButton();
    try {
      const config = await request("/api/config");
      if (typeof config.github_configured !== "boolean" || typeof config.llm_configured !== "boolean") {
        throw new Error("Invalid connection settings.");
      }
      state.config = config;
      state.configStatus = "ready";
      $("github-status").textContent = state.config.github_configured ? "Token ready" : "Public access";
      $("llm-status").textContent = state.config.llm_configured ? "Ready" : "Not configured";
      $("github-dot").classList.add("connected");
      $("llm-dot").classList.toggle("connected", state.config.llm_configured);
      $("model-name").textContent = state.config.llm_configured ? state.config.model : "Demo runs without API keys";
      $("app-version").textContent = `v${state.config.version}`;
    } catch {
      state.configStatus = "error";
      state.config = null;
      $("github-status").textContent = "Unavailable";
      $("llm-status").textContent = "Unavailable";
      $("model-name").textContent = "Connection status unavailable";
    } finally {
      $("retry-config").disabled = false;
      renderConnectionNotice();
      renderDetails();
    }
  }

  function renderConnectionNotice() {
    const live = state.mode === "live";
    const unavailable = state.configStatus !== "ready" || !state.config?.llm_configured;
    $("config-notice").hidden = state.configStatus !== "error" && !(live && unavailable);
    $("retry-config").hidden = state.configStatus !== "error";
    $("config-notice-message").textContent = state.configStatus === "error"
      ? "Couldn’t check API configuration. Demo still works. Check again to enable live analysis."
      : state.configStatus === "loading" ? "Checking API configuration…"
      : "Live issue loading works without an LLM key. Set OPENAI_API_KEY in .env and restart to enable analysis.";
  }

  function resetFilters() {
    $("issue-search").value = "";
    $("category-filter").value = "all";
    $("priority-filter").value = "all";
  }

  function setMode(mode) {
    if (mode === state.mode) return;
    if (state.mode === "live") state.liveRepository = $("repository").value.trim();
    issueRequest?.abort();
    analysisRequest?.abort();
    state.mode = mode;
    state.loadingAnalysis = false;
    state.loadingIssues = false;
    state.issues = [];
    state.selectedNumber = null;
    $("demo-mode").classList.toggle("selected", mode === "demo");
    $("live-mode").classList.toggle("selected", mode === "live");
    $("demo-mode").setAttribute("aria-pressed", String(mode === "demo"));
    $("live-mode").setAttribute("aria-pressed", String(mode === "live"));
    $("repository").readOnly = mode === "demo";
    $("repository").value = mode === "demo" ? (state.config?.demo_repository || "repopilot/taskboard") : state.liveRepository;
    state.repository = $("repository").value;
    $("mode-description").textContent = mode === "demo"
      ? "Explore sample issues and pre-written analyses. No API keys needed."
      : "Read GitHub issues and analyze them with your configured LLM API.";
    $("source-badge").textContent = mode === "demo" ? "SAMPLE DATA" : "LIVE GITHUB";
    $("source-badge").classList.toggle("live", mode === "live");
    $("source-notice").textContent = mode === "demo"
      ? "Demo uses fictional issues and pre-written analysis. Live mode reads GitHub and uses your configured LLM API."
      : "Repository content is sent to the LLM provider when you analyze an issue. Suggestions stay here until you choose to use them.";
    $("inbox-source").textContent = mode === "demo" ? "DEMO" : "LIVE";
    $("inbox-footer-text").textContent = mode === "demo" ? "Sample repository · no GitHub changes" : "Read-only access · no GitHub changes";
    $("workspace-error").hidden = true;
    $("analysis-error").hidden = true;
    resetFilters();
    renderConnectionNotice();
    renderIssues();
    renderDetails();
    renderStats();
    setIssuesLoading(false);
    if (mode === "demo" || state.liveRepository) {
      loadIssues();
    } else {
      $("repository").focus();
      announce("Live mode selected. Enter a repository to load its issues.");
    }
  }

  function setIssuesLoading(loading) {
    state.loadingIssues = loading;
    $("load-issues").disabled = loading;
    $("load-issues").querySelector("span").textContent = loading ? "Loading…" : "Load issues";
    $("issue-list").setAttribute("aria-busy", String(loading));
    $("retry-issues").disabled = loading;
    $("repository").disabled = loading;
    $("issue-state").disabled = loading;
  }

  function parseRepository(value) {
    let repository = value.trim();
    if (repository.startsWith("https://")) {
      try {
        const url = new URL(repository);
        if (url.protocol !== "https:" || url.host !== "github.com" || url.username || url.password || url.search || url.hash) return null;
        repository = url.pathname.replace(/^\/+|\/+$/g, "");
      } catch { return null; }
    } else {
      repository = repository.replace(/\/+$/, "");
    }
    repository = repository.replace(/\.git$/, "");
    if (!/^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}\/[a-zA-Z0-9_.-]{1,100}$/.test(repository)) return null;
    return [".", ".."].includes(repository.split("/")[1]) ? null : repository;
  }

  async function loadIssues() {
    const repository = parseRepository($("repository").value);
    if (!repository) {
      $("workspace-error-message").textContent = "Enter owner/repository or a GitHub repository URL, for example https://github.com/pallets/flask.";
      $("workspace-error").hidden = false;
      $("repository").focus();
      return;
    }
    issueRequest?.abort();
    analysisRequest?.abort();
    const controller = new AbortController();
    issueRequest = controller;
    state.loadingAnalysis = false;
    state.repository = repository;
    state.issues = [];
    state.selectedNumber = null;
    document.querySelector(".original-report").open = false;
    if (state.mode === "live") state.liveRepository = repository;
    $("workspace-error").hidden = true;
    $("analysis-error").hidden = true;
    setIssuesLoading(true);
    renderIssues();
    renderDetails();
    renderStats();
    const query = new URLSearchParams({ repository, state: $("issue-state").value, limit: "30", mode: state.mode });
    try {
      const data = await request(`/api/issues?${query}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!Array.isArray(data.issues) || typeof data.repository !== "string") throw new Error("The server returned an invalid issue list. Try again.");
      state.issues = data.issues;
      state.repository = data.repository;
      $("repository").value = data.repository;
      if (state.mode === "live") {
        state.liveRepository = data.repository;
        const prefix = `live:${data.repository.toLowerCase()}:`;
        for (const key of state.analyses.keys()) {
          if (key.startsWith(prefix)) state.analyses.delete(key);
        }
      }
      $("source-notice").textContent = data.notice || $("source-notice").textContent;
      resetFilters();
      state.selectedNumber = state.issues[0]?.number ?? null;
      setIssuesLoading(false);
      renderIssues();
      renderDetails();
      renderStats();
      announce(`${state.issues.length} issues loaded from ${state.repository}.`);
      if (state.mode === "demo" && state.selectedNumber !== null && !selectedAnalysis()) await analyzeIssue();
    } catch (error) {
      if (error.name === "AbortError" || controller.signal.aborted) return;
      $("workspace-error-message").textContent = error.message;
      $("workspace-error").hidden = false;
      setIssuesLoading(false);
      renderIssues();
      announce("Issues could not be loaded.");
    } finally {
      if (issueRequest === controller) setIssuesLoading(false);
    }
  }

  function filteredIssues() {
    const search = $("issue-search").value.trim().toLowerCase().replace(/^#/, "");
    const category = $("category-filter").value;
    const priority = $("priority-filter").value;
    $("filter-note").hidden = category === "all" && priority === "all";
    return state.issues.filter((issue) => {
      const analysis = analysisForIssue(issue.number)?.analysis;
      if (category !== "all" && analysis?.category !== category) return false;
      if (priority !== "all" && analysis?.priority !== priority) return false;
      return !search || `${issue.number} ${issue.title} ${issue.body}`.toLowerCase().includes(search);
    });
  }

  function renderLabels(container, labels) {
    container.replaceChildren();
    for (const label of labels || []) container.append(element("span", "label", label));
  }

  function renderIssues() {
    const list = $("issue-list");
    const focusedIssue = document.activeElement?.dataset.issueNumber;
    list.replaceChildren();
    const issues = filteredIssues();
    $("visible-count").textContent = issues.length;
    if (state.loadingIssues) {
      const message = element("div", "list-empty");
      message.append(element("strong", "", "Loading the inbox…"), element("span", "", "Reading repository issues."));
      list.append(message);
      return;
    }
    if (!issues.length) {
      const empty = element("div", "list-empty");
      const noMatches = state.issues.length > 0;
      empty.append(element("strong", "", noMatches ? "No matching issues" : "Your inbox is clear"));
      empty.append(element("span", "", noMatches ? "Try another search or reset the filters." : state.mode === "live" && !state.repository ? "Enter a repository above to get started." : "Load a repository or choose another issue state."));
      if (noMatches) {
        const clear = element("button", "text-button", "Reset filters");
        clear.type = "button";
        clear.addEventListener("click", () => {
          resetFilters();
          renderIssues();
          $("issue-search").focus();
        });
        empty.append(element("br"), clear);
      }
      list.append(empty);
      return;
    }
    for (const issue of issues) {
      const item = element("div", "issue-item");
      item.setAttribute("role", "listitem");
      const button = element("button", "issue-button");
      button.type = "button";
      button.dataset.issueNumber = issue.number;
      button.setAttribute("aria-controls", "issue-detail");
      button.classList.toggle("selected", issue.number === state.selectedNumber);
      button.setAttribute("aria-pressed", String(issue.number === state.selectedNumber));
      button.setAttribute("aria-label", `Issue ${issue.number}: ${issue.title}`);
      const top = element("span", "issue-row-top");
      top.append(element("span", "issue-number", `#${issue.number}`));
      if (analysisForIssue(issue.number)) top.append(element("span", "analysis-indicator", "Analyzed"));
      const labels = element("span", "issue-card-labels");
      renderLabels(labels, (issue.labels || []).slice(0, 3));
      const bottom = element("span", "issue-row-bottom");
      bottom.append(element("span", "", formatDate(issue.updated_at)), element("span", "comment-count", `${issue.comments ?? 0}`));
      button.append(top, element("span", "issue-title", issue.title), labels, bottom);
      button.addEventListener("click", () => selectIssue(issue.number));
      item.append(button);
      list.append(item);
    }
    if (focusedIssue) list.querySelector(`[data-issue-number="${focusedIssue}"]`)?.focus({ preventScroll: true });
  }

  function selectIssue(number) {
    if (number === state.selectedNumber) return;
    analysisRequest?.abort();
    state.loadingAnalysis = false;
    state.selectedNumber = number;
    document.querySelector(".original-report").open = false;
    $("analysis-error").hidden = true;
    renderIssues();
    renderDetails();
    announce(`Selected issue ${number}.`);
  }

  function safeGitHubUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && url.hostname === "github.com" && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }

  function updateAnalyzeButton() {
    const issue = selectedIssue();
    const unavailable = state.mode === "live" && (state.configStatus !== "ready" || !state.config?.llm_configured);
    const button = $("analyze-issue");
    button.disabled = !issue || state.loadingAnalysis || unavailable;
    button.setAttribute("aria-busy", String(state.loadingAnalysis));
    button.querySelector("span").textContent = state.loadingAnalysis ? "Analyzing…" : selectedAnalysis() ? "Analyze again" : "Analyze issue";
    button.title = unavailable ? state.configStatus === "ready" ? "Set OPENAI_API_KEY and restart RepoPilot to enable live analysis." : "Check API configuration to enable live analysis." : "";
    $("retry-analysis").disabled = state.loadingAnalysis || unavailable;
  }

  function renderDetails() {
    const issue = selectedIssue();
    $("detail-empty").hidden = Boolean(issue);
    $("issue-detail").hidden = !issue;
    $("issue-detail").setAttribute("aria-busy", String(state.loadingAnalysis));
    updateAnalyzeButton();
    if (!issue) return;
    $("detail-number").textContent = `ISSUE #${issue.number}`;
    $("detail-state").textContent = issue.state;
    $("detail-state").classList.toggle("closed", issue.state === "closed");
    $("detail-title").textContent = issue.title;
    $("detail-meta").textContent = `Opened by ${issue.author || "unknown"} · ${formatDate(issue.created_at)} · ${issue.comments ?? 0} comments`;
    renderLabels($("original-labels"), issue.labels);
    $("issue-body").textContent = issue.body || "No issue description provided.";
    $("truncated-notice").hidden = !issue.body_truncated;
    const url = state.mode === "live" ? safeGitHubUrl(issue.html_url) : null;
    $("github-link").hidden = !url;
    if (url) $("github-link").href = url;
    else $("github-link").removeAttribute("href");
    const result = selectedAnalysis();
    $("analysis-result").hidden = !result || state.loadingAnalysis;
    $("analysis-loading").hidden = !state.loadingAnalysis;
    $("analysis-placeholder").hidden = Boolean(result) || state.loadingAnalysis;
    const unavailable = state.mode === "live" && (state.configStatus !== "ready" || !state.config?.llm_configured);
    $("analysis-provenance").textContent = state.loadingAnalysis
      ? (state.mode === "demo" ? "Loading the pre-written sample analysis." : "Sending this issue to your LLM provider.")
      : result ? provenance(result) : unavailable ? state.configStatus === "ready" ? "Set OPENAI_API_KEY and restart to enable live analysis." : "Check API configuration to enable live analysis." : state.mode === "demo" ? "Pre-written sample analysis · no LLM request" : "Ready when you are. Analysis sends this issue to the LLM provider.";
    if (result) renderAnalysis(result);
  }

  function provenance(result) {
    if (result.provider === "demo") return "Pre-written sample analysis · no LLM request";
    return `AI suggestions · ${result.model || "configured model"}${result.cached ? " · cached result" : ""}`;
  }

  function renderList(container, values, emptyMessage) {
    container.replaceChildren();
    if (!values?.length) {
      container.append(element("li", "empty-list", emptyMessage));
      return;
    }
    for (const value of values) container.append(element("li", "", value));
  }

  function renderAnalysis(result) {
    const analysis = result.analysis;
    $("analysis-summary").textContent = analysis.summary;
    $("analysis-rationale").textContent = analysis.rationale;
    $("category-pill").textContent = categoryNames[analysis.category] || analysis.category;
    $("category-pill").dataset.category = analysis.category;
    $("priority-pill").textContent = `${analysis.priority} priority`;
    $("priority-pill").dataset.priority = analysis.priority;
    renderLabels($("suggested-labels"), analysis.suggested_labels);
    if (!analysis.suggested_labels?.length) $("suggested-labels").append(element("span", "filter-note", "No labels suggested"));
    renderList($("missing-info"), analysis.missing_info, "No additional context requested.");
    renderList($("next-steps"), analysis.next_steps, "No next steps suggested.");
    $("draft-reply").textContent = analysis.draft_reply;
    $("result-source").textContent = result.provider === "demo" ? "SAMPLE ANALYSIS · Review suggestions before use" : `AI-GENERATED · ${result.model || "LLM API"} · Review before use`;
  }

  async function analyzeIssue() {
    const issue = selectedIssue();
    if (!issue || state.loadingAnalysis) return;
    if (state.mode === "live" && (state.configStatus !== "ready" || !state.config?.llm_configured)) return;
    analysisRequest?.abort();
    const controller = new AbortController();
    analysisRequest = controller;
    const key = analysisKey(issue.number);
    const repository = state.repository;
    const mode = state.mode;
    state.loadingAnalysis = true;
    $("analysis-error").hidden = true;
    $("analysis-loading-text").textContent = state.mode === "demo" ? "Loading the pre-written sample analysis…" : "Reading the issue and preparing suggestions…";
    renderDetails();
    announce(`Preparing analysis for issue ${issue.number}.`);
    try {
      const result = await request("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository, issue_number: issue.number, mode }),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (result.issue?.number !== issue.number || result.repository?.toLowerCase() !== repository.toLowerCase() || result.mode !== mode || !result.analysis) {
        throw new Error("The analysis response did not match this issue. Try again.");
      }
      state.issues = state.issues.map((item) => item.number === result.issue.number ? result.issue : item);
      saveAnalysis(key, result);
      state.loadingAnalysis = false;
      renderDetails();
      renderIssues();
      renderStats();
      announce(`Analysis ready for issue ${issue.number}.`);
    } catch (error) {
      if (error.name === "AbortError" || controller.signal.aborted) return;
      state.loadingAnalysis = false;
      renderDetails();
      $("analysis-error-message").textContent = error.message;
      $("analysis-error").hidden = false;
      announce(`Analysis failed for issue ${issue.number}.`);
    } finally {
      if (analysisRequest === controller) {
        state.loadingAnalysis = false;
        updateAnalyzeButton();
      }
    }
  }

  function renderStats() {
    const results = state.issues.map((issue) => analysisForIssue(issue.number)).filter(Boolean);
    $("issue-count").textContent = state.issues.length;
    $("analysis-count").textContent = results.length;
    $("priority-count").textContent = results.filter((result) => result.analysis.priority === "high").length;
    $("issue-count-description").textContent = state.loadingIssues ? "Loading repository…" : state.issues.length ? (state.mode === "demo" ? "From the sample repository" : "From GitHub · up to 30 issues") : "No issues loaded";
  }

  async function copyReply() {
    const reply = selectedAnalysis()?.analysis.draft_reply;
    if (!reply) { expireAnalyses(); renderDetails(); return; }
    const key = analysisKey(state.selectedNumber);
    const number = state.selectedNumber;
    let clipboardTimeout;
    try {
      await Promise.race([
        navigator.clipboard.writeText(reply),
        new Promise((resolve, reject) => {
          clipboardTimeout = setTimeout(() => reject(new Error("Clipboard timed out.")), 2000);
        }),
      ]);
      toast(`Reply for #${number} copied. Review it before posting.`);
    } catch {
      if (key !== analysisKey(state.selectedNumber) || selectedAnalysis()?.analysis.draft_reply !== reply) {
        toast("The selected issue changed. Copy the current draft again.");
        return;
      }
      const selection = window.getSelection();
      if (!selection) { toast("Select the reply text and copy it manually."); return; }
      const range = document.createRange();
      range.selectNodeContents($("draft-reply"));
      selection.removeAllRanges();
      selection.addRange(range);
      toast("Draft selected. Press Ctrl+C or ⌘C to copy.");
    } finally {
      clearTimeout(clipboardTimeout);
    }
  }

  function downloadJson() {
    const result = selectedAnalysis();
    if (!result) { expireAnalyses(); renderDetails(); return; }
    const blob = new Blob([JSON.stringify(result, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = `repopilot-${result.repository.replace(/[^a-zA-Z0-9_-]/g, "-")}-issue-${result.issue.number}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Analysis exported as JSON.");
  }

  $("demo-mode").addEventListener("click", () => setMode("demo"));
  $("live-mode").addEventListener("click", () => setMode("live"));
  $("repository-form").addEventListener("submit", (event) => { event.preventDefault(); loadIssues(); });
  $("retry-issues").addEventListener("click", loadIssues);
  $("retry-config").addEventListener("click", loadConfig);
  $("analyze-issue").addEventListener("click", analyzeIssue);
  $("retry-analysis").addEventListener("click", analyzeIssue);
  $("issue-search").addEventListener("input", renderIssues);
  $("category-filter").addEventListener("change", renderIssues);
  $("priority-filter").addEventListener("change", renderIssues);
  $("copy-reply").addEventListener("click", copyReply);
  $("download-json").addEventListener("click", downloadJson);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) expireAnalyses(); });
  setInterval(expireAnalyses, 60 * 1000);

  Promise.allSettled([loadConfig(), loadIssues()]);
})();
