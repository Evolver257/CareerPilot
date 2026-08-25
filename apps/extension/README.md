# CareerPilot Browser Extension

Phase 8/9 provides a WXT extension boundary for structured Browser Actions. The extension does not upload cookies, passwords, or authentication tokens.

The background entrypoint connects to:

```text
ws://localhost:8010/api/browser-tasks/ws/{task_id}
```

The content script only matches the local Mock Platform fixture. It resolves semantic actions such as `CLICK` with `target.name = "立即投递"`, reports structured results, and leaves CAPTCHA/login/risk-control/unknown-state handling to the user. The CareerBoard adapter prototype does not expand this match scope to external sites.
