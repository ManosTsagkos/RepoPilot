# Demo walkthrough

This walkthrough uses offline samples. No API keys or network requests are required. The analyses in demo mode are pre-written examples, not newly generated model responses.

1. Start the app with `python -m repopilot` and open `http://127.0.0.1:8000`.
2. Keep demo mode selected and load the sample issues.
3. Select a bug report and inspect its title, body, and existing labels.
4. Run the analysis. Review the suggested category, priority, and rationale.
5. Check the missing information and next steps against the issue body.
6. Copy the draft reply, then export the analysis as JSON.
7. Select a different sample to compare how a feature request or question is handled.

## Demonstrating live mode

Set `OPENAI_API_KEY` in `.env`, restart the server, and switch to live mode. Use a public repository with a clear issue you can discuss. A GitHub token is optional for public reads.

Fetch the issues and select one to analyze. Explain that the application sends the selected issue to the model, validates the returned JSON, and displays the result for review. Avoid using a private issue in a screen recording unless you have permission to share its content.

## Points to discuss

- Why output validation matters when a browser expects a stable response shape.
- How authentication errors, rate limits, timeouts, and malformed model output reach the user.
- Why the application retries some GitHub reads but does not automatically retry a paid LLM request.
- How the cache prevents repeat calls while allowing changed issue text to produce a new analysis.
- Where the model's context stops: one issue does not provide enough evidence to verify a code-level diagnosis.

## Small evaluation exercise

Choose five to ten issues across bugs, features, and questions. Before running the model, write your expected category, broad priority, and the main missing details. Compare the output with those notes.

Record incorrect assumptions and unsupported statements as well as helpful suggestions. Revise a prompt or schema only after identifying a repeated issue, then re-run the same examples. Demo output is useful for checking the interface, but it should not be counted as evidence of model quality.
