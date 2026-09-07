import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "./page";
import { createCampaign, updateCampaign } from "../../lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../../lib/api", () => ({
  getResumes: vi.fn().mockResolvedValue({ items: [{ id: "resume", name: "Resume", is_default: true }] }),
  getCampaigns: vi.fn().mockResolvedValue({ items: [{ id: "plan", name: "Draft", status: "DRAFT", min_score: 50, max_jobs: 10, filters: {}, target_cities: [], scoring_mode: "fast" }] }),
  createCampaign: vi.fn().mockResolvedValue({ id: "new" }), updateCampaign: vi.fn().mockResolvedValue({ id: "plan" }),
}));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
});
it("allows clearing the count and validates before creating a 200-job plan", async () => {
  render(<Page />);
  await screen.findByRole("option", { name: "Resume（默认）" });
  const input = screen.getByRole("spinbutton", { name: "最大职位数" });
  fireEvent.change(input, { target: { value: "" } });
  expect(input).toHaveValue(null);
  fireEvent.click(screen.getByRole("button", { name: "创建投递计划" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("1–200");
  expect(createCampaign).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: "创建投递计划" }));
  await waitFor(() => expect(createCampaign).toHaveBeenCalledWith(expect.objectContaining({ max_jobs: 200 })));
});
it("focuses edit fields and displays validation in the edit panel", async () => {
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  const panel = screen.getByRole("region", { name: "编辑投递计划" });
  expect(within(panel).getByRole("textbox", { name: "计划名称" })).toHaveFocus();
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  fireEvent.change(within(panel).getByRole("spinbutton", { name: "最多职位数" }), { target: { value: "3.5" } });
  fireEvent.click(within(panel).getByRole("button", { name: "保存修改" }));
  expect(await within(panel).findByRole("alert")).toHaveTextContent("1–200");
  expect(updateCampaign).not.toHaveBeenCalled();
});
