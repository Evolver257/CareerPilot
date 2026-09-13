import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createKnowledgeIndexRun: vi.fn(),
  getKnowledgeHealth: vi.fn(),
}));

vi.mock("../lib/api", () => api);

import { KnowledgeBaseMaintenancePanel } from "./knowledge-base-maintenance-panel";

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  api.getKnowledgeHealth.mockResolvedValue({
    status: "needs_update",
    ready: false,
    jobs_total: 232,
    document_count: 229,
    indexed_jobs: 229,
    compatible_jobs: 229,
    needs_update_jobs: 3,
    chunk_count: 916,
    embedded_chunk_count: 916,
    embedding_model: "Qwen/Qwen3-Embedding-0.6B",
    embedding_dimensions: 1024,
    updated_at: "2026-09-11T00:00:00Z",
    latest_run: null,
  });
  api.createKnowledgeIndexRun.mockResolvedValue({
    id: "run-1",
    mode: "incremental",
    status: "PENDING",
    progress: 0,
    processed_jobs: 0,
    total_jobs: 3,
    error: null,
  });
});

describe("KnowledgeBaseMaintenancePanel", () => {
  it("shows index health in system maintenance language", async () => {
    render(<KnowledgeBaseMaintenancePanel />);

    expect(await screen.findByRole("region", { name: "岗位知识库维护" })).toBeInTheDocument();
    expect(screen.getByText("229")).toBeInTheDocument();
    expect(screen.getAllByText("916")).toHaveLength(2);
    expect(screen.getByText("Qwen/Qwen3-Embedding-0.6B")).toBeInTheDocument();
  });

  it("starts an incremental maintenance run from settings", async () => {
    render(<KnowledgeBaseMaintenancePanel />);

    fireEvent.click(await screen.findByRole("button", { name: "更新 3 个岗位" }));

    await waitFor(() => expect(api.createKnowledgeIndexRun).toHaveBeenCalledWith({
      mode: "incremental",
      auto_start: true,
    }));
    expect(await screen.findByText("知识库正在更新")).toBeInTheDocument();
  });
});
