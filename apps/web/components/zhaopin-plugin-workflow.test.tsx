import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ZhaopinPluginWorkflow } from "./zhaopin-plugin-workflow";
import { createCuratedCampaign } from "../lib/api";
vi.mock("../lib/api", () => ({ createCuratedCampaign: vi.fn(), getResumes: vi.fn().mockResolvedValue({ items: [{ id: "resume", name: "默认简历", is_default: true }] }) }));
const jobs = [
  { id: "low", title: "低匹配岗位", score: 30, education: "本科" },
  { id: "high", title: "高匹配岗位", score: 80, education: "硕士" },
];
function update(extra: Record<string, unknown> = {}) {
  act(() => window.dispatchEvent(new MessageEvent("message", { source: window, data: {
    source: "careerpilot-extension", type: "ZHAOPIN_TASK_STATE", request_id: "poll",
    task: { request_id: "run", status: "RUNNING", search_url: "https://www.zhaopin.com/sou?kw=AI",
      target_count: 100, quick_score_threshold: 50, resume_id: "resume", jobs,
      created_count: 2, updated_count: 0, updated_at: new Date().toISOString(), ...extra },
  } })));
}
describe("Zhaopin background progress", () => {
  afterEach(cleanup);
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });
  it("persists manual selections across remounts and creates only the selected candidates without delivering", async () => {
    vi.mocked(createCuratedCampaign).mockResolvedValue({ id: "plan" } as Awaited<ReturnType<typeof createCuratedCampaign>>);
    const post = vi.spyOn(window, "postMessage");
    const view = render(<ZhaopinPluginWorkflow />);
    update({ status: "COMPLETED" });
    fireEvent.click(await screen.findByRole("checkbox", { name: "选择高匹配岗位" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择低匹配岗位" }));
    view.unmount();
    render(<ZhaopinPluginWorkflow />);
    update({ status: "COMPLETED" });
    expect(await screen.findByRole("checkbox", { name: "选择低匹配岗位" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "选择高匹配岗位" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "用所选 1 个岗位创建计划" }));
    await screen.findByRole("link", { name: "查看投递计划并确认 →" });
    expect(createCuratedCampaign).toHaveBeenCalledWith(expect.objectContaining({ job_ids: ["low"], resume_id: "resume" }));
    expect(screen.getByRole("button", { name: "已创建投递计划" })).toBeDisabled();
    expect(post.mock.calls.some(([value]) => /LAUNCH|SEARCH_REQUEST/.test(value.type))).toBe(false);
  });
  it("preserves selection after a plan creation error and allows retry", async () => {
    vi.mocked(createCuratedCampaign).mockRejectedValueOnce(new Error("暂时不可用")).mockResolvedValueOnce({ id: "retry-plan" } as Awaited<ReturnType<typeof createCuratedCampaign>>);
    render(<ZhaopinPluginWorkflow />);
    update({ status: "COMPLETED" });
    fireEvent.click(await screen.findByRole("button", { name: "用所选 1 个岗位创建计划" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时不可用");
    expect(screen.getByRole("checkbox", { name: "选择高匹配岗位" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "用所选 1 个岗位创建计划" }));
    expect(await screen.findByRole("link", { name: "查看投递计划并确认 →" })).toHaveAttribute("href", "/campaigns/retry-plan");
  });
  it("sorts low scores last, defaults them off, preserves manual choices during progress updates", async () => {
    render(<ZhaopinPluginWorkflow />);
    update();
    const checkboxes = await screen.findAllByRole("checkbox");
    expect(checkboxes[0]).toHaveAccessibleName("选择高匹配岗位");
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();
    fireEvent.click(checkboxes[1]);
    update({ jobs: [...jobs, { id: "new", title: "新增岗位", score: 70 }] });
    expect(screen.getByRole("checkbox", { name: "选择低匹配岗位" })).toBeChecked();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "3");
  });
  it("allows stop/resume and does not overwrite edited quantity with stale completed-task snapshots", async () => {
    const post = vi.spyOn(window, "postMessage");
    render(<ZhaopinPluginWorkflow />);
    update({ status: "WAITING_FOR_USER", error: "需要验证码" });
    fireEvent.click(await screen.findByRole("button", { name: "继续采集" }));
    expect(post.mock.calls.some(([value]) => value.type === "ZHAOPIN_SEARCH_RESUME_REQUEST")).toBe(true);
    update({ status: "COMPLETED" });
    const count = screen.getByRole("spinbutton", { name: "最多采集（1–200）" });
    fireEvent.change(count, { target: { value: "80" } });
    update({ status: "COMPLETED", updated_at: "later" });
    await waitFor(() => expect(count).toHaveValue(80));
  });
  it("accepts a city name and builds the corresponding Zhaopin city search URL", async () => {
    render(<ZhaopinPluginWorkflow />);
    update({ search_url: "https://www.zhaopin.com/sou?jl=530&kw=AI" });
    const city = await screen.findByLabelText("城市");
    fireEvent.change(city, { target: { value: "成都" } });
    expect(screen.getByRole("link", { name: "预览搜索条件 ↗" })).toHaveAttribute("href", "https://www.zhaopin.com/sou?jl=801&kw=AI");
  });
  it("explains when a city cannot be converted instead of sending an invalid URL", async () => {
    render(<ZhaopinPluginWorkflow />);
    update();
    const city = await screen.findByLabelText("城市");
    fireEvent.change(city, { target: { value: "不存在的城市" } });
    expect(screen.queryByRole("link", { name: "预览搜索条件 ↗" })).not.toBeInTheDocument();
    expect(screen.getByText(/暂未识别/)).toBeInTheDocument();
  });
});
