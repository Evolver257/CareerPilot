import React from "react";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobDetailPage from "../app/jobs/[id]/page";
import { analyzeJob, getJob, getJobs, type Job } from "../lib/api";
import { jobDescription, jobSalary } from "../lib/job-presentation";
import { ZhaopinJobDescription } from "./zhaopin-job-description";

let currentId = "zp";
vi.mock("next/navigation", () => ({ useParams: () => ({ id: currentId }) }));
vi.mock("../lib/api", () => ({ getJob: vi.fn(), getJobs: vi.fn(), analyzeJob: vi.fn() }));
const sample = {
  id: "zp", platform: "zhaopin", title: "智联算法工程师",
  description: "智联算法工程师\nCompany: 示例公司\nSalary: 200-300元/天\n岗位职责\n1、开发 RAG 系统\n岗位基本需求\n1、熟悉 Python",
  source_url: "https://www.zhaopin.com/jobdetail/CC123.htm", location: "北京",
  salary_min: 200, salary_max: 300, education_requirement: "Education: 硕士",
  raw_data: { description_source: "detail_page", company_name: "示例公司", salary_text: "200-300元/天",
    salary_source: "search_card", education: "硕士", experience: "经验不限", skills: ["Python", "RAG"],
    company_summary: "20-99人 · 软件服务", company_description: "公司专注知识检索", work_address: "北京***" },
  last_collected_at: "2020-01-01", created_at: "2020-01-01", updated_at: "2020-01-01",
} as unknown as Job;

afterEach(() => { cleanup(); vi.clearAllMocks(); });
beforeEach(() => { currentId = "zp"; vi.mocked(getJobs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 }); });
describe("Zhaopin job detail presentation", () => {
  it("shows JD without import prefixes, real headings, numbered requirements and separate company information", () => {
    render(<ZhaopinJobDescription job={sample} />);
    const jd = screen.getByRole("region", { name: "智联职位描述" });
    expect(within(jd).getByRole("heading", { name: "岗位基本需求" })).toBeInTheDocument();
    expect(jd.querySelector("ol")).not.toBeNull();
    expect(within(jd).queryByText(/Company:/)).toBeNull();
    expect(within(jd).queryByText("公司专注知识检索")).toBeNull();
    expect(screen.getByText("公司专注知识检索")).toBeInTheDocument();
    expect(screen.getByText(/平台仅公开了部分地址/)).toBeInTheDocument();
  });
  it("does not call masked salary negotiable or show historical raw JD over user edits", () => {
    expect(jobSalary({ ...sample, raw_data: { salary_text: "**-**元", salary_visibility: "masked" } })).toBe("薪资未公开");
    expect(jobSalary(sample)).toBe("200-300元/天");
    expect(jobDescription({ ...sample, description: "用户修改后的 JD", raw_data: { description: "旧 JD" } })).toBe("用户修改后的 JD");
  });
  it("keeps full JD visible when analysis fails, with Zhaopin-specific source labels", async () => {
    vi.mocked(getJob).mockResolvedValue(sample);
    vi.mocked(analyzeJob).mockRejectedValue(new Error("解析暂不可用"));
    render(<JobDetailPage />);
    expect(await screen.findByRole("heading", { name: "智联算法工程师", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText(/解析暂不可用/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "智联职位描述" })).toBeVisible();
    expect(screen.getByRole("link", { name: "智联招聘原页面" })).toHaveAttribute("href", sample.source_url);
    expect(screen.getByText("学历 · 硕士")).toBeInTheDocument();
    expect(screen.queryByText(/BOSS/)).toBeNull();
    expect(screen.queryByText("职位分析已就绪")).toBeNull();
  });
  it("does not display stale analysis or a delayed previous job after navigation", async () => {
    let resolveOld: (job: Job) => void = () => {};
    vi.mocked(getJob).mockImplementation((id) => id === "zp" ? new Promise<Job>((resolve) => { resolveOld = resolve; }) : Promise.resolve({ ...sample, id: "new", title: "新的智联岗位" }));
    vi.mocked(analyzeJob).mockRejectedValue(new Error("暂不可用"));
    const view = render(<JobDetailPage />);
    currentId = "new";
    view.rerender(<JobDetailPage />);
    expect(await screen.findByRole("heading", { name: "新的智联岗位", level: 1 })).toBeInTheDocument();
    await act(async () => resolveOld(sample));
    expect(screen.queryByRole("heading", { name: "智联算法工程师", level: 1 })).toBeNull();
  });
});
