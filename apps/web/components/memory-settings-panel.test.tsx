import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  batchDeleteAgentMemories: vi.fn(),
  cancelAgentMemoryEmbeddingRun: vi.fn(),
  clearAgentMemories: vi.fn(),
  createAgentMemoryEmbeddingRun: vi.fn(),
  deleteAgentMemory: vi.fn(),
  downloadAgentMemoryExport: vi.fn(),
  getAgentMemories: vi.fn(),
  getAgentMemoryCandidates: vi.fn(),
  getAgentMemoryEmbeddingRuns: vi.fn(),
  getAgentMemoryEmbeddingHealth: vi.fn(),
  getAgentMemoryHistory: vi.fn(),
  getAgentMemorySettings: vi.fn(),
  markAgentMemoryOutdated: vi.fn(),
  resolveAgentMemoryCandidate: vi.fn(),
  retryAgentMemoryEmbeddingRun: vi.fn(),
  runAgentMemoryMaintenance: vi.fn(),
  restoreAgentMemory: vi.fn(),
  updateAgentMemory: vi.fn(),
  updateAgentMemorySettings: vi.fn(),
}));

vi.mock("../lib/api", () => api);

import { MemorySettingsPanel } from "./memory-settings-panel";

afterEach(cleanup);

function memory(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    memory_type: "SKILL_BACKGROUND",
    memory_key: `skill.${id}`,
    structured_value: {},
    scope: null,
    memory_class: "SEMANTIC",
    stability: "STABLE",
    importance: 0.7,
    status: "ACTIVE",
    content: `技能 ${id}`,
    source_quote: `我会 ${id}`,
    extraction_method: "RULE",
    extraction_version: "v2",
    supersedes_id: null,
    last_verified_at: null,
    pinned: false,
    use_count: 0,
    confidence: 0.9,
    user_confirmed: false,
    sensitivity: "NORMAL",
    provenance: {},
    valid_until: null,
    last_used_at: null,
    deleted_at: null,
    deleted_from_status: null,
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getAgentMemorySettings.mockResolvedValue({
    enabled: true,
    auto_save_non_sensitive: false,
    retention_days: 180,
    allowed_types: ["SKILL_BACKGROUND"],
    allow_session_summaries: false,
    allow_unconfirmed_context: false,
    memory_token_budget: 700,
    extraction_confidence_threshold: 0.75,
  });
  api.getAgentMemories.mockResolvedValue({
    items: [memory("python")],
    total: 21,
    limit: 20,
    offset: 0,
    has_more: true,
  });
  api.getAgentMemoryCandidates.mockResolvedValue({ items: [], total: 0 });
  api.getAgentMemoryEmbeddingRuns.mockResolvedValue([]);
  api.getAgentMemoryEmbeddingHealth.mockResolvedValue({
    embedding_model: "Qwen/Qwen3-Embedding-0.6B",
    embedding_dimensions: 1024,
    provider_available: true,
    status: "ready",
    total: 1,
    embedded: 1,
    pending: 0,
    failed: 0,
    latest_run: null,
  });
  api.updateAgentMemory.mockResolvedValue(memory("python", { user_confirmed: true }));
});

describe("MemorySettingsPanel", () => {
  it("loads the next page and keeps the total count visible", async () => {
    render(<MemorySettingsPanel />);
    expect(await screen.findByText("第 1 页 · 21 条")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(api.getAgentMemories).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20, limit: 20 })));
  });

  it("explains automatic maintenance without a manual confirmation action", async () => {
    render(<MemorySettingsPanel />);
    expect(await screen.findByText("自动维护已启用")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认使用" })).not.toBeInTheDocument();
  });

  it("starts a maintenance scan from the memory controls", async () => {
    render(<MemorySettingsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "维护记忆" }));
    await waitFor(() => expect(api.runAgentMemoryMaintenance).toHaveBeenCalledTimes(1));
  });
});
