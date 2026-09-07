# Legacy Worker scaffold

This folder is the original placeholder and is **not** used by Docker Compose.
The production independent worker now runs `python -m app.worker`, built from
`services/api`, so it shares the tested models, migrations and business services
without duplicating them. API and Worker remain separate processes/containers.

See [the worker runbook](../../docs/evaluation-worker-runbook.md) and
`services/api/tests/test_worker_postgres.py` for real fault-injection tests.
Do not use the old Dockerfile as a replacement for the configured Worker service.
