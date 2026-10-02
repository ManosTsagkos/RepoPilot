# Architecture

RepoPilot is a local FastAPI application. The backend serves the dashboard and JSON API from the same origin, keeps credentials out of the browser, and owns both external API clients.

## Request flow

1. The browser requests an issue list for a repository, state, and mode.
2. In demo mode, the backend reads local sample data. In live mode, it calls the GitHub Issues REST API, sorted by most recently updated. It returns up to 30 issues and scans at most three pages of 100 entries, including pull requests. This bounded list is not a full repository audit.
3. GitHub responses are normalized into the application's issue model. Pull requests are excluded, and issue text is limited to 16,000 characters.
4. The browser requests an analysis for a selected issue number. The backend loads that issue and checks its analysis cache.
5. In live mode, the backend sends the selected issue to the OpenAI Responses API with a structured output schema. Demo mode returns a pre-written analysis.
6. Pydantic validates the analysis. The browser displays it and provides copy and JSON export controls.

The generated fields are `summary`, `category`, `priority`, `rationale`, `suggested_labels`, `missing_info`, `next_steps`, and `draft_reply`. Enum values and bounds keep the output predictable. Validation failures become API errors rather than partially trusted analyses.

## External services

**GitHub.** Public repositories can be read anonymously. An optional `GITHUB_TOKEN` enables authenticated requests and access to private repositories covered by that token. The client uses timeouts and limited retries for network errors, server errors, and rate limits with a short retry delay. It does not blindly wait through long rate-limit windows.

**OpenAI.** The client uses the Responses API and JSON Schema structured output. It treats a refusal, an incomplete response, or an invalid JSON result as an analysis failure. The backend does not automatically retry a paid analysis request: a retry could create a second charge after an ambiguous failure. A user can explicitly try again.

Both clients use HTTPS with certificate verification through Python's default SSL context, including installed Windows certificate authorities. Certificate verification stays enabled.

## Cache

Analyses are cached in memory for 15 minutes by default, with a maximum of 128 entries. Cache identity includes the repository, normalized issue, a hash of its original full body, and model. Changes after the body truncation boundary therefore invalidate the prior result too. The cache is process-local and disappears on restart.

Live analysis runs one request at a time. A second request that cannot acquire the analysis lock promptly receives an `analysis_busy` error and can be retried later.

## Trust and privacy

Issue titles and bodies are external, untrusted text. The analysis instructions tell the model to treat that text as data, avoid following instructions inside an issue, and avoid inventing repository context. Structured output constrains response shape; it does not guarantee correct reasoning.

Only the selected issue's content and metadata are sent for live analysis. The application does not upload repository source code or fetch the full discussion history. Environment variables are read by the server; configuration responses expose readiness rather than secret values. The dashboard displays text using safe DOM operations.

The API performs read-only GitHub operations. A suggested label or reply is shown for review and never applied automatically.

The server accepts local hostnames and rejects browser POST requests whose Origin does not match the local application. Those guards help protect a local session; they are not user authentication. CLI requests without an Origin header are supported. Security headers restrict the dashboard to same-origin assets, prevent framing, and keep API responses out of browser caches.

## Why this scope

A small backend and vanilla dashboard make the integration easy to run, inspect, and debug. A database, account system, background queue, and write access to GitHub would add substantial operational work without improving the initial issue-review workflow. Those are possible extensions if the project grows.

Before hosting a shared instance, add authentication, request and cost limits, a suitable secret store, and a policy for storing issue data. You would also need to deliberately configure trusted hosts and proxy/origin handling for that deployment. The included configuration is intended for local use.
