"use client";
import { developerMode } from "../../lib/workspaces";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import {
  deleteJob,
  getRecruitmentPlatforms,
  getJobs,
  importJobs,
  updateJob,
  type Job,
  type JobListResponse,
  type RecruitmentPlatform,
} from "../../lib/api";
import { formatJobCollectionTime, isJobFreshForAutoDelivery } from "../../lib/job-freshness";

const DEFAULT_PAGE_SIZE = 20;
const platformLabels: Record<string, string> = {
  boss: "BOSS 直聘",
  zhaopin: "智联招聘",
  manual: "手动导入",
  mock: "演示数据",
};

type JobSearchFilters = {
  search: string;
  company: string;
  location: string;
  platform: string;
  education: string;
  experience: string;
  salaryFloor: string;
  salaryCeiling: string;
};

const EMPTY_FILTERS: JobSearchFilters = {
  search: "",
  company: "",
  location: "",
  platform: "",
  education: "",
  experience: "",
  salaryFloor: "",
  salaryCeiling: "",
};

function jobQueryOptions(filters: JobSearchFilters, page: number, pageSize: number) {
  return {
    search: filters.search.trim() || undefined,
    company: filters.company.trim() || undefined,
    location: filters.location.trim() || undefined,
    platform: filters.platform || undefined,
    education: filters.education || undefined,
    experience: filters.experience.trim() || undefined,
    salary_floor: filters.salaryFloor ? Number(filters.salaryFloor) : undefined,
    salary_ceiling: filters.salaryCeiling ? Number(filters.salaryCeiling) : undefined,
    page,
    page_size: pageSize,
  };
}

function visiblePageNumbers(current: number, total: number): number[] {
  const pages = new Set([1, total]);
  for (let value = current - 2; value <= current + 2; value += 1) {
    if (value >= 1 && value <= total) pages.add(value);
  }
  return [...pages].sort((left, right) => left - right);
}

function descriptionSummary(title: string, description: string): string {
  const lines = description.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines.find((line) => (
    line !== title
    && !/^(Company|Location|Salary):/i.test(line)
    && !/^[#【\[]*(岗位职责|工作职责|职位描述|任职要求|工作要求|职责)[】\]：:\s#]*$/.test(line)
  )) ?? "查看完整职位描述";
}

function compactRequirement(value: string | null, kind: "education" | "experience"): string | null {
  const text = value?.trim();
  if (!text) return null;
  const patterns = kind === "education"
    ? [/博士(?:及以上)?/, /硕士(?:及以上)?/, /本科(?:及以上)?/, /大专(?:及以上)?/, /学历不限/, /不限学历/]
    : [/经验不限/, /不限经验/, /应届(?:生)?/, /在校生?/, /无经验/, /\d+\s*[-至]\s*\d+\s*年/, /\d+\s*年以上/];
  const matched = patterns.map((pattern) => text.match(pattern)?.[0]).find(Boolean);
  if (matched) return matched;
  return text.length > 14 ? `${text.slice(0, 14)}…` : text;
}

export default function JobsPage() {
  const [platforms, setPlatforms] = useState<RecruitmentPlatform[]>([]);
  const [draftFilters, setDraftFilters] = useState<JobSearchFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<JobSearchFilters>(EMPTY_FILTERS);
  const [jobs, setJobs] = useState<JobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawJd, setRawJd] = useState("");
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [jumpPage, setJumpPage] = useState("");
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editLocation, setEditLocation] = useState("");
  const [editSalaryMin, setEditSalaryMin] = useState("");
  const [editSalaryMax, setEditSalaryMax] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());

  async function refreshJobs() {
    const response = await getJobs(jobQueryOptions(appliedFilters, page, pageSize));
    const lastPage = Math.max(1, Math.ceil(response.total / response.page_size));
    if (page > lastPage) {
      setPage(lastPage);
      return;
    }
    setJobs(response);
  }

  useEffect(() => {
    getRecruitmentPlatforms().then(setPlatforms).catch(() => setPlatforms([]));
  }, []);

  useEffect(() => {
    setSelectedJobIds(new Set());
    let cancelled = false;
    setLoading(true);
    setError(null);
    getJobs(jobQueryOptions(appliedFilters, page, pageSize))
      .then((response) => {
        if (!cancelled) setJobs(response);
      })
      .catch(() => {
        if (!cancelled) setError("无法加载职位，请确认 API 服务已启动。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [appliedFilters, page, pageSize]);

  async function handleImport() {
    if (!rawJd.trim()) {
      setError("请先粘贴一份原始 JD。");
      return;
    }
    setImporting(true);
    setError(null);
    setMessage(null);
    try {
      const result = await importJobs({ mode: "single", raw_jd: rawJd.trim(), platform: "manual" });
      setMessage(`已导入 ${result.created} 条职位，跳过 ${result.duplicates} 条重复数据。`);
      setRawJd("");
      const refreshed = await getJobs(jobQueryOptions(appliedFilters, page, pageSize));
      setJobs(refreshed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位导入失败。");
    } finally {
      setImporting(false);
    }
  }

  async function handleMockImport() {
    setImporting(true);
    setError(null);
    setMessage(null);
    try {
      const result = await importJobs({ mode: "mock", limit: 30 });
      setMessage(`Mock Dataset：新增 ${result.created} 条职位，跳过 ${result.duplicates} 条重复数据。`);
      const refreshed = await getJobs(jobQueryOptions(appliedFilters, page, pageSize));
      setJobs(refreshed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Mock 职位导入失败。");
    } finally {
      setImporting(false);
    }
  }

  function beginEdit(job: Job) {
    setEditingJob(job);
    setEditTitle(job.title);
    setEditLocation(job.location ?? "");
    setEditSalaryMin(job.salary_min?.toString() ?? "");
    setEditSalaryMax(job.salary_max?.toString() ?? "");
    setEditDescription(job.description);
  }

  async function handleSaveJob() {
    if (!editingJob || !editTitle.trim() || !editDescription.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await updateJob(editingJob.id, {
        title: editTitle.trim(),
        location: editLocation.trim() || null,
        salary_min: editSalaryMin ? Number(editSalaryMin) : null,
        salary_max: editSalaryMax ? Number(editSalaryMax) : null,
        description: editDescription.trim(),
      });
      await refreshJobs();
      setEditingJob(null);
      setMessage("职位信息已保存并重新解析。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteJob(job: Job) {
    if (!window.confirm(`确定删除职位“${job.title}”吗？已进入投递计划的职位不会被删除。`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteJob(job.id);
      setSelectedJobIds((current) => {
        const next = new Set(current);
        next.delete(job.id);
        return next;
      });
      await refreshJobs();
      if (editingJob?.id === job.id) setEditingJob(null);
      setMessage("职位已删除。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位删除失败。");
    } finally {
      setSaving(false);
    }
  }

  function toggleJobSelection(jobId: string) {
    setSelectedJobIds((current) => {
      const next = new Set(current);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  function toggleCurrentPageSelection() {
    const pageJobIds = jobs?.items.map((job) => job.id) ?? [];
    if (pageJobIds.length === 0) return;
    setSelectedJobIds((current) => {
      const next = new Set(current);
      const shouldSelect = pageJobIds.some((jobId) => !next.has(jobId));
      pageJobIds.forEach((jobId) => {
        if (shouldSelect) next.add(jobId);
        else next.delete(jobId);
      });
      return next;
    });
  }

  async function handleDeleteSelected() {
    const ids = [...selectedJobIds];
    if (ids.length === 0) return;
    if (!window.confirm(`确定删除选中的 ${ids.length} 个职位吗？已进入投递计划的职位不会被删除。`)) return;

    setBulkDeleting(true);
    setError(null);
    setMessage(null);
    try {
      const results = await Promise.allSettled(ids.map((jobId) => deleteJob(jobId)));
      const failedIds = ids.filter((_, index) => results[index]?.status === "rejected");
      const deletedCount = ids.length - failedIds.length;
      setSelectedJobIds(new Set(failedIds));
      await refreshJobs();
      if (failedIds.length > 0) {
        setError(`已删除 ${deletedCount} 个职位，${failedIds.length} 个职位未删除；已进入投递计划的职位会被保留。`);
      } else {
        setMessage(`已删除 ${deletedCount} 个职位。`);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "批量删除职位失败。");
    } finally {
      setBulkDeleting(false);
    }
  }

  function updateDraftFilter<Key extends keyof JobSearchFilters>(key: Key, value: JobSearchFilters[Key]) {
    setDraftFilters((current) => ({ ...current, [key]: value }));
  }

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const salaryFloor = draftFilters.salaryFloor ? Number(draftFilters.salaryFloor) : null;
    const salaryCeiling = draftFilters.salaryCeiling ? Number(draftFilters.salaryCeiling) : null;
    if (salaryFloor !== null && salaryCeiling !== null && salaryFloor > salaryCeiling) {
      setError("可接受薪资下限不能高于上限。");
      return;
    }
    setError(null);
    setMessage(null);
    setPage(1);
    setJumpPage("");
    setAppliedFilters({
      ...draftFilters,
      search: draftFilters.search.trim(),
      company: draftFilters.company.trim(),
      location: draftFilters.location.trim(),
      experience: draftFilters.experience.trim(),
    });
  }

  function resetSearch() {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(1);
    setJumpPage("");
    setError(null);
  }

  function jumpToPage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!jobs) return;
    const totalPages = Math.max(1, Math.ceil(jobs.total / jobs.page_size));
    const requested = Number(jumpPage);
    if (!Number.isFinite(requested)) return;
    setPage(Math.min(totalPages, Math.max(1, Math.trunc(requested))));
    setJumpPage("");
  }

  const activeFilterLabels = [
    appliedFilters.search && `关键词：${appliedFilters.search}`,
    appliedFilters.company && `公司：${appliedFilters.company}`,
    appliedFilters.location && `城市：${appliedFilters.location}`,
    appliedFilters.platform && `来源：${platformLabels[appliedFilters.platform] ?? appliedFilters.platform}`,
    appliedFilters.education && `学历：${appliedFilters.education}`,
    appliedFilters.experience && `经验：${appliedFilters.experience}`,
    appliedFilters.salaryFloor && `薪资不低于 ${appliedFilters.salaryFloor}`,
    appliedFilters.salaryCeiling && `薪资不高于 ${appliedFilters.salaryCeiling}`,
  ].filter((label): label is string => Boolean(label));
  const totalPages = jobs ? Math.max(1, Math.ceil(jobs.total / jobs.page_size)) : 1;
  const pageNumbers = visiblePageNumbers(page, totalPages);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Job Explorer</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">职位探索</h1>
          <p className="mt-3 text-slate-500">搜索与查看已标准化的职位，为后续智能分析做好准备。</p>
        </div>
        <div className="rounded-full bg-white px-4 py-2 text-sm text-slate-500 shadow-sm">
          {jobs?.total ?? 0} 个职位
        </div>
      </header>

      <section className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><p className="eyebrow">条件搜索</p><h2 className="mt-2 text-xl font-semibold">找到更合适的职位</h2><p className="mt-2 text-sm text-slate-500">组合多个条件后统一搜索，输入内容不会在每次按键时打断浏览。</p></div>
          {activeFilterLabels.length > 0 && <button className="text-sm font-medium text-indigo-700" onClick={resetSearch} type="button">清除全部条件</button>}
        </div>
        <form className="mt-6 space-y-5" onSubmit={applySearch}>
          <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_180px] [&>*]:min-w-0">
            <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-search">关键词
              <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="job-filter-search" maxLength={100} onChange={(event) => updateDraftFilter("search", event.target.value)} placeholder="职位名称、技能或 JD 内容，例如 RAG、机器人算法" value={draftFilters.search} />
            </label>
            <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-location">城市 / 地区
              <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="job-filter-location" maxLength={100} onChange={(event) => updateDraftFilter("location", event.target.value)} placeholder="北京、上海、远程" value={draftFilters.location} />
            </label>
            <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-platform">职位来源
              <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="job-filter-platform" onChange={(event) => updateDraftFilter("platform", event.target.value)} value={draftFilters.platform}>
                <option value="">全部来源</option>{platforms.map((platform) => <option key={platform.id} value={platform.id}>{platform.name}</option>)}<option value="manual">手动导入</option><option value="mock">演示数据</option>
              </select>
            </label>
          </div>
          <button aria-controls="job-more-filters" aria-expanded={showMoreFilters} className="text-sm font-medium text-indigo-700" onClick={() => setShowMoreFilters((current) => !current)} type="button">
            {showMoreFilters ? "收起更多筛选 ↑" : `更多筛选${[draftFilters.company, draftFilters.education, draftFilters.experience, draftFilters.salaryFloor, draftFilters.salaryCeiling].some(Boolean) ? " · 已填写" : " ↓"}`}
          </button>
          {showMoreFilters && <div className="grid min-w-0 gap-4 border-t border-slate-100 pt-5 md:grid-cols-2 xl:grid-cols-4" id="job-more-filters">
            <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-company">公司
              <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="job-filter-company" maxLength={100} onChange={(event) => updateDraftFilter("company", event.target.value)} placeholder="公司名称" value={draftFilters.company} />
            </label>
            <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-education">学历要求
              <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="job-filter-education" onChange={(event) => updateDraftFilter("education", event.target.value)} value={draftFilters.education}>
                <option value="">不限学历</option><option value="大专">大专</option><option value="本科">本科</option><option value="硕士">硕士</option><option value="博士">博士</option>
              </select>
            </label>
            <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-experience">经验要求
              <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="job-filter-experience" maxLength={100} onChange={(event) => updateDraftFilter("experience", event.target.value)} placeholder="应届、1-3 年、经验不限" value={draftFilters.experience} />
            </label>
            <div className="grid min-w-0 grid-cols-2 gap-2 [&>*]:min-w-0">
              <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-salary-floor">薪资下限
                <input className="mt-2 min-w-0 w-full rounded-xl border border-slate-200 px-3 py-3 font-normal outline-none focus:border-indigo-500" id="job-filter-salary-floor" min={0} onChange={(event) => updateDraftFilter("salaryFloor", event.target.value)} placeholder="最低" type="number" value={draftFilters.salaryFloor} />
              </label>
              <label className="text-sm font-medium text-slate-700" htmlFor="job-filter-salary-ceiling">薪资上限
                <input className="mt-2 min-w-0 w-full rounded-xl border border-slate-200 px-3 py-3 font-normal outline-none focus:border-indigo-500" id="job-filter-salary-ceiling" min={0} onChange={(event) => updateDraftFilter("salaryCeiling", event.target.value)} placeholder="最高" type="number" value={draftFilters.salaryCeiling} />
              </label>
            </div>
          </div>}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
            <p className="text-xs leading-5 text-slate-500">薪资条件按职位解析后的数值区间匹配；未填写的条件不会参与筛选。</p>
            <div className="flex gap-2"><button className="rounded-xl border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" onClick={resetSearch} type="button">重置</button><button className="rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={loading} type="submit">{loading ? "查询中…" : "搜索职位"}</button></div>
          </div>
        </form>
        {activeFilterLabels.length > 0 && <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4"><span className="text-xs font-medium text-slate-500">已应用</span>{activeFilterLabels.map((label) => <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700" key={label}>{label}</span>)}</div>}
      </section>

      <details className="panel group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4"><div><p className="eyebrow">Job Intelligence</p><h2 className="mt-2 text-lg font-semibold">导入与解析 JD</h2><p className="mt-1 text-sm text-slate-500">需要手动补充职位时再展开，不干扰日常检索。</p></div><span className="text-sm font-medium text-indigo-700 group-open:hidden">展开 →</span><span className="hidden text-sm font-medium text-indigo-700 group-open:inline">收起 ↑</span></summary>
        <div className="mt-5 border-t border-slate-100 pt-5">
          {developerMode && <div className="flex justify-end"><button className="rounded-xl border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50" disabled={importing} onClick={() => void handleMockImport()} type="button">导入演示职位</button></div>}
          <textarea className="mt-4 min-h-28 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setRawJd(event.target.value)} placeholder="粘贴原始职位描述，系统会提取标题、技能、经验、学历与职责。" value={rawJd} />
          <button className="mt-3 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={importing} onClick={() => void handleImport()} type="button">{importing ? "处理中…" : "导入并解析"}</button>
        </div>
      </details>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {message && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">{message}</div>}

      {editingJob && <section className="panel border-indigo-200">
        <div className="flex items-start justify-between gap-4"><div><p className="eyebrow">维护职位</p><h2 className="mt-2 text-xl font-semibold">编辑职位信息</h2></div><button className="text-sm text-slate-500" onClick={() => setEditingJob(null)} type="button">关闭</button></div>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">职位名称<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal" onChange={(event) => setEditTitle(event.target.value)} value={editTitle} /></label>
          <label className="text-sm font-medium text-slate-700">地点<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal" onChange={(event) => setEditLocation(event.target.value)} value={editLocation} /></label>
          <label className="text-sm font-medium text-slate-700">最低薪资<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal" min="0" onChange={(event) => setEditSalaryMin(event.target.value)} type="number" value={editSalaryMin} /></label>
          <label className="text-sm font-medium text-slate-700">最高薪资<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal" min="0" onChange={(event) => setEditSalaryMax(event.target.value)} type="number" value={editSalaryMax} /></label>
        </div>
        <label className="mt-4 block text-sm font-medium text-slate-700">职位描述（JD）<textarea className="mt-2 min-h-64 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal leading-6" onChange={(event) => setEditDescription(event.target.value)} value={editDescription} /></label>
        <div className="mt-4 flex gap-2"><button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={saving || !editTitle.trim() || !editDescription.trim()} onClick={() => void handleSaveJob()} type="button">{saving ? "保存中…" : "保存职位"}</button><button className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700" onClick={() => setEditingJob(null)} type="button">取消</button></div>
      </section>}

      <section className="panel overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 bg-slate-50/80 px-5 py-4 sm:px-6">
          <div>
            <p className="text-sm font-semibold text-slate-800">职位列表</p>
            <p className="mt-1 text-xs text-slate-500">共 {jobs?.total ?? 0} 个结果{jobs && jobs.total > 0 ? ` · 当前第 ${jobs.page} / ${totalPages} 页` : ""}</p>
          </div>
          {jobs && jobs.items.length > 0 && <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex cursor-pointer items-center gap-2 text-slate-600">
              <input checked={jobs.items.every((job) => selectedJobIds.has(job.id))} className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" onChange={toggleCurrentPageSelection} type="checkbox" />
              <span>全选本页</span>
            </label>
            {selectedJobIds.size > 0 && <span className="text-slate-500">已选 {selectedJobIds.size} 个</span>}
            {selectedJobIds.size > 0 && <button className="rounded-lg bg-rose-600 px-3 py-2 font-medium text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={bulkDeleting || saving} onClick={() => void handleDeleteSelected()} type="button">{bulkDeleting ? "删除中…" : "批量删除"}</button>}
            {selectedJobIds.size > 0 && <button className="rounded-lg border border-slate-200 px-3 py-2 text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700" disabled={bulkDeleting} onClick={() => setSelectedJobIds(new Set())} type="button">清空选择</button>}
          </div>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] table-fixed text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium tracking-wide text-slate-500">
              <tr>
                <th className="w-12 px-5 py-3.5 sm:px-6"><span className="sr-only">选择</span></th>
                <th className="w-[38%] px-5 py-3.5 sm:px-6">职位信息</th>
                <th className="w-[17%] px-5 py-3.5 sm:px-6">薪资与地点</th>
                <th className="w-[22%] px-5 py-3.5 sm:px-6">来源与时效</th>
                <th className="w-[16%] px-5 py-3.5 sm:px-6">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && <tr><td className="px-6 py-10 text-center text-slate-500" colSpan={7}>加载中…</td></tr>}
              {!loading && jobs?.items.length === 0 && <tr><td className="px-6 py-12 text-center text-slate-500" colSpan={7}><p className="font-medium text-slate-700">没有找到符合条件的职位</p><p className="mt-2 text-sm">尝试减少筛选条件，或重置后查看全部职位。</p>{activeFilterLabels.length > 0 && <button className="mt-4 font-medium text-indigo-700" onClick={resetSearch} type="button">清除筛选条件</button>}</td></tr>}
              {!loading && jobs?.items.map((job) => {
                const freshForDelivery = isJobFreshForAutoDelivery(job);
                const companyName = typeof job.raw_data.company_name === "string" ? job.raw_data.company_name : "公司未提供";
                const salaryDisplay = typeof job.raw_data.salary_text === "string"
                  ? job.raw_data.salary_text
                  : job.salary_min || job.salary_max
                    ? `${job.salary_min ?? "?"} - ${job.salary_max ?? "?"}`
                    : "薪资面议";
                return (
                <tr key={job.id} className="group transition-colors hover:bg-slate-50">
                  <td className="px-5 py-5 align-top sm:px-6"><input aria-label={`选择职位：${job.title}`} checked={selectedJobIds.has(job.id)} className="mt-1 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" onChange={() => toggleJobSelection(job.id)} type="checkbox" /></td>
                  <td className="min-w-0 px-5 py-5 align-top sm:px-6">
                    <Link className="block truncate font-semibold text-indigo-700 transition-colors hover:text-indigo-900" href={`/jobs/${job.id}`} title={job.title}>
                      {job.title}
                    </Link>
                    <p className="mt-1 truncate text-sm text-slate-600" title={companyName}>{companyName}</p>
                    <p className="mt-2 truncate text-xs text-slate-400" title={descriptionSummary(job.title, job.description)}>{descriptionSummary(job.title, job.description)}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {compactRequirement(job.education_requirement, "education") && <span className="max-w-[11rem] truncate rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700" title={`学历要求：${job.education_requirement}`}>学历 · {compactRequirement(job.education_requirement, "education")}</span>}
                      {compactRequirement(job.experience_requirement, "experience") && <span className="max-w-[11rem] truncate rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600" title={`经验要求：${job.experience_requirement}`}>经验 · {compactRequirement(job.experience_requirement, "experience")}</span>}
                    </div>
                  </td>
                  <td className="min-w-0 px-5 py-5 align-top sm:px-6">
                    <span className="block truncate font-semibold text-slate-800" title={salaryDisplay}>{salaryDisplay}</span>
                    <span className="mt-2 block truncate text-xs text-slate-500" title={job.location ?? undefined}>{job.location ?? "地点未注明"}</span>
                  </td>
                  <td className="min-w-0 px-5 py-5 align-top sm:px-6"><span className="inline-flex max-w-full truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600">{platformLabels[job.platform] ?? job.platform}</span><p className={`mt-2 truncate text-xs font-medium ${freshForDelivery ? "text-emerald-700" : "text-amber-700"}`}>{freshForDelivery ? "● 可纳入投递" : "● 需重新采集"}</p><p className="mt-1 truncate text-xs text-slate-400" title={formatJobCollectionTime(job)}>采集于 {formatJobCollectionTime(job)}</p></td>
                  <td className="min-w-0 px-5 py-5 align-top sm:px-6"><div className="flex flex-wrap items-center gap-x-2 gap-y-1"><Link className="rounded-lg border border-indigo-200 px-2.5 py-1.5 text-xs font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-50" href={`/jobs/${job.id}`}>详情</Link><button className="text-xs font-medium text-slate-500 transition hover:text-indigo-700" disabled={bulkDeleting} onClick={() => beginEdit(job)} type="button">编辑</button><button className="text-xs font-medium text-rose-600 transition hover:text-rose-700" disabled={saving || bulkDeleting} onClick={() => void handleDeleteJob(job)} type="button">删除</button></div></td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {jobs && jobs.total > 0 && <div className="border-t border-slate-200 px-6 py-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3 text-slate-500"><span>共 {jobs.total} 个职位 · 第 {jobs.page}/{totalPages} 页</span><label className="flex items-center gap-2">每页<select aria-label="每页职位数" className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-slate-700" onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} value={pageSize}><option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select>条</label></div>
            <div className="flex flex-wrap items-center gap-2">
              <button aria-label="上一页" className="rounded-lg border border-slate-200 px-3 py-2 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">上一页</button>
              {pageNumbers.map((pageNumber, index) => <span className="flex items-center gap-2" key={pageNumber}>{index > 0 && pageNumber - pageNumbers[index - 1] > 1 && <span className="px-1 text-slate-400">…</span>}<button aria-current={pageNumber === page ? "page" : undefined} aria-label={`第 ${pageNumber} 页`} className={`min-w-10 rounded-lg border px-3 py-2 font-medium transition ${pageNumber === page ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-200 text-slate-700 hover:border-indigo-300 hover:text-indigo-700"}`} disabled={loading} onClick={() => setPage(pageNumber)} type="button">{pageNumber}</button></span>)}
              <button aria-label="下一页" className="rounded-lg border border-slate-200 px-3 py-2 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} type="button">下一页</button>
              {totalPages > 1 && <form className="ml-1 flex items-center gap-2" onSubmit={jumpToPage}><span className="text-slate-500">跳至</span><input aria-label="跳转页码" className="w-16 rounded-lg border border-slate-200 px-2 py-2 text-center outline-none focus:border-indigo-500" max={totalPages} min={1} onChange={(event) => setJumpPage(event.target.value)} placeholder={String(page)} type="number" value={jumpPage} /><button className="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-700" type="submit">确定</button></form>}
            </div>
          </div>
        </div>}
      </section>
    </div>
  );
}
