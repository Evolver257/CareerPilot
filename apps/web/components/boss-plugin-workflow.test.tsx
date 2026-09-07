import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BossPluginWorkflow } from "./boss-plugin-workflow";

vi.mock("../lib/api", () => ({
  approveCampaignJobs: vi.fn(),
  createCampaignBrowserTasks: vi.fn(),
  createCuratedCampaign: vi.fn(),
  getResumes: vi.fn().mockResolvedValue({ items: [] }),
  importBossVisibleJobs: vi.fn(),
  quickScoreJobs: vi.fn(),
}));

function dispatchExtensionMessage(data: Record<string, unknown>) {
  window.dispatchEvent(new MessageEvent("message", {
    data: { source: "careerpilot-extension", ...data },
    source: window,
  }));
}

describe("BossPluginWorkflow collection cancellation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lets the user stop an active collection and keeps persisted progress", async () => {
    const postMessage = vi.spyOn(window, "postMessage");
    render(<BossPluginWorkflow onTasksCreated={vi.fn().mockResolvedValue(undefined)} />);

    act(() => dispatchExtensionMessage({
      type: "BOSS_EXTENSION_PONG",
      request_id: "ping",
      version: "0.2.8",
    }));

    fireEvent.click(await screen.findByRole("button", { name: "调动插件搜索 BOSS" }));
    fireEvent.click(await screen.findByRole("button", { name: "停止采集" }));
    expect(screen.getByRole("dialog", { name: "确定停止当前采集任务？" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认停止" }));
    const cancelCall = postMessage.mock.calls.find(([message]) => (
      message as { type?: string }
    ).type === "BOSS_SEARCH_CANCEL_REQUEST");
    expect(cancelCall).toBeDefined();
    const requestId = (cancelCall?.[0] as { request_id: string }).request_id;

    act(() => dispatchExtensionMessage({
      type: "BOSS_SEARCH_CANCEL_RESULT",
      request_id: requestId,
      success: true,
      task: {
        request_id: requestId,
        status: "CANCELLED",
        requirements: "AI Agent RAG 实习",
        city: "北京",
        target_count: 10,
        collected_count: 4,
        persisted_count: 3,
        created_count: 3,
        updated_count: 0,
        detailed_count: 3,
        page_url: "https://www.zhipin.com/web/geek/jobs",
        page_state: "READY",
        persisted_jobs: [],
        started_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      },
    }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText(/职位采集已停止：已读取 4\/10，已持久化 3 条/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停止采集" })).not.toBeInTheDocument();
  });
});
