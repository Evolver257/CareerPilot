# CareerPilot Browser Extension

Phase 8/9 provides a WXT extension boundary for structured Browser Actions. The extension does not upload cookies, passwords, or authentication tokens.

The background entrypoint connects to:

```text
ws://localhost:8010/api/browser-tasks/ws/{task_id}
```

The content script matches CareerPilot local pages, the Mock Platform fixture, and BOSS 直聘 pages. `/browser-tasks` can use a scoped `window.postMessage` bridge to ask the extension to open a structured BOSS search or a backend-generated BrowserTask URL. Recruitment search, collection, and delivery now always use a visible foreground tab; the extension never intentionally scrapes or clicks in an inactive hidden tab. If the user switches away while collection is running, the page reports `TAB_HIDDEN` and pauses until the user brings the recruitment tab back and explicitly continues. Collection uses deterministic, rate-limited one-card scrolling and emits each structured job as a progress event; the extension background persists every progress item directly to CareerPilot and stores a lightweight recoverable task summary. Campaign batches run sequentially in one reusable visible tab and advance only after the backend confirms the current task is terminal. On BOSS pages, the popup and page workflow collect only currently visible structured job cards; they never upload cookies, passwords, tokens, or raw HTML. BOSS application actions still require an explicit user approval, and CAPTCHA/login/risk-control/unknown-state handling pauses for the user.
