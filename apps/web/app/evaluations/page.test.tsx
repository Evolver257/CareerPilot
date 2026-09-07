import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import Page from "./page";

const fixture = vi.hoisted(() => ({
  dataset: {
    id: "seed-dataset",
    name: "Tool seed",
    suite: "tool_calling" as const,
    version: "seed-v1",
    label_status: "seed",
    sha256: "hash",
    case_count: 10,
    created_at: "2026-09-07T00:00:00Z",
  },
  run: {
    id: "legacy-run",
    dataset_id: "seed-dataset",
    status: "SUCCEEDED",
    configuration: {},
    result: {
      summary: { completion_rate: 0 },
      cases: [{ case_id: "tool-001", task_completed: false, invalid_call_rate: 1 }],
    },
    progress_current: 10,
    progress_total: 10,
    error: null,
    started_at: "2026-09-07T00:00:00Z",
    finished_at: "2026-09-07T00:01:00Z",
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:01:00Z",
  },
}));

vi.mock("../../lib/api", () => ({
  compareEvaluationRuns: vi.fn(),
  createEvaluationRun: vi.fn(),
  getEvaluationDatasets: vi.fn().mockResolvedValue([fixture.dataset]),
  getEvaluationRun: vi.fn().mockResolvedValue(fixture.run),
  getEvaluationRuns: vi.fn().mockResolvedValue([fixture.run]),
  importToolEvaluationSeed: vi.fn(),
  updateEvaluationRun: vi.fn(),
}));

afterEach(cleanup);

it("marks legacy runs from a non-gold dataset as pipeline-only results", async () => {
  render(<Page />);
  expect(await screen.findByText("非金标链路测试，不代表模型质量")).toBeInTheDocument();
  expect(screen.getByText("失败案例 · 1")).toBeInTheDocument();
});
