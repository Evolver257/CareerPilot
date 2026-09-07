import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AutomationWorkspace from "../../components/automation-workspace";
import { createCampaignBrowserTasks, getApplications } from "../../lib/api";
import { launchDeliveryTasks } from "../../lib/delivery-bridge";
vi.mock("../../lib/delivery-bridge", () => ({ launchDeliveryTasks: vi.fn().mockResolvedValue(2) }));
const Page = () => <AutomationWorkspace view="delivery" />;

vi.mock("../../components/boss-plugin-workflow", () => ({ BossPluginWorkflow: () => null }));
vi.mock("../../components/zhaopin-plugin-workflow", () => ({ ZhaopinPluginWorkflow: () => null }));
vi.mock("../../lib/api", () => ({
  getApplications: vi.fn(), getBrowserTaskCampaigns: vi.fn().mockResolvedValue({ items: [] }),
  getCampaigns: vi.fn().mockResolvedValue({ items: [{ id: "plan", name: "混合计划", scoring_mode: "fast" }] }),
  createCampaignBrowserTasks: vi.fn(),
}));
function applications(platforms: string[]) {
  return { items: platforms.map((platform) => ({ id: platform, campaign_id: "plan", job_id: platform, status: "QUEUED", platform,
    job: { title: `${platform}岗位`, last_collected_at: new Date().toISOString(), source_url: "https://www.zhaopin.com/jobdetail/test" },
  })) } as Awaited<ReturnType<typeof getApplications>>;
}
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(launchDeliveryTasks).mockResolvedValue(2);
  vi.mocked(createCampaignBrowserTasks).mockImplementation(async ({ platform }) => ({
    items: [{ id: platform, platform, payload: { actions: [{ url: `https://${platform}.example/?task=${platform}` }] } }],
    failed_count: 0, created_count: 1, reused_count: 0,
  }) as unknown as Awaited<ReturnType<typeof createCampaignBrowserTasks>>);
});
it("launches mixed platforms in a single queue and keeps unsupported platforms manual", async () => {
  vi.mocked(getApplications).mockResolvedValue(applications(["boss", "zhaopin", "other"]));
  render(<Page />);
  const button = await screen.findByRole("button", { name: "一键投递 2 个排队岗位" });
  expect(screen.getByRole("link", { name: "打开岗位原页 ↗" })).toHaveAttribute("href", "https://www.zhaopin.com/jobdetail/test");
  fireEvent.click(button);
  await waitFor(() => expect(launchDeliveryTasks).toHaveBeenCalledTimes(1));
  expect(createCampaignBrowserTasks).toHaveBeenCalledTimes(2);
  for (const platform of ["boss", "zhaopin"]) expect(createCampaignBrowserTasks).toHaveBeenCalledWith({ campaign_id: "plan", platform, scenario: "SUCCESS", auto_start: false });
  expect(vi.mocked(launchDeliveryTasks).mock.calls[0][0].map((item) => item.platform)).toEqual(["boss", "zhaopin"]);
  await screen.findByText(/扩展已接收 2 个新任务/);
});
it("does not offer automatic delivery for unsupported platforms", async () => {
  vi.mocked(getApplications).mockResolvedValue(applications(["other"]));
  render(<Page />);
  await screen.findByText("1 个岗位需手动投递");
  const button = screen.getByRole("button", { name: "一键投递 0 个排队岗位" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(createCampaignBrowserTasks).not.toHaveBeenCalled();
});
it("supports Zhaopin-only plans but does not claim success without extension acknowledgement", async () => {
  vi.mocked(getApplications).mockResolvedValue(applications(["zhaopin"]));
  vi.mocked(launchDeliveryTasks).mockRejectedValue(new Error("未收到扩展确认"));
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "一键投递 1 个排队岗位" }));
  await screen.findByText("未收到扩展确认");
  expect(createCampaignBrowserTasks).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/扩展已接收/)).not.toBeInTheDocument();
});
it("launches remaining tasks when one platform fails", async () => {
  vi.mocked(getApplications).mockResolvedValue(applications(["boss", "zhaopin"]));
  vi.mocked(createCampaignBrowserTasks).mockRejectedValueOnce(new Error("BOSS 创建失败"));
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "一键投递 2 个排队岗位" }));
  await screen.findByText("BOSS 创建失败");
  expect(vi.mocked(launchDeliveryTasks).mock.calls[0][0].map((item) => item.platform)).toEqual(["zhaopin"]);
});
