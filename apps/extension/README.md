# CareerPilot Browser Extension

Phase 8/9 provides a WXT extension boundary for structured Browser Actions. The extension does not upload cookies, passwords, or authentication tokens.

The background entrypoint connects to:

```text
ws://localhost:8010/api/browser-tasks/ws/{task_id}
```

The content script matches CareerPilot local pages, the Mock Platform fixture, and BOSS 直聘 pages. `/browser-tasks` can use a scoped `window.postMessage` bridge to ask the extension to open a structured BOSS search or a backend-generated BrowserTask URL. Search and collection open BOSS in a new inactive tab so the user remains on CareerPilot while the content script works. Collection uses deterministic, rate-limited one-card scrolling and emits each structured job as a progress event; the extension background persists every progress item directly to CareerPilot and stores a lightweight recoverable task summary, so collection continues when the user leaves `/browser-tasks`. Campaign batches run sequentially in one reusable inactive BOSS tab and advance only after the backend confirms the current task is terminal. On BOSS pages, the popup and page workflow collect only currently visible structured job cards; they never upload cookies, passwords, tokens, or raw HTML. BOSS application actions still require an explicit user approval, and CAPTCHA/login/risk-control/unknown-state handling pauses for the user.
