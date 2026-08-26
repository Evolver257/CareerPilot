"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  deleteJob,
  getJobs,
  importJobs,
  updateJob,
  type Job,
  type JobListResponse,
} from "../../lib/api";

const PAGE_SIZE = 20;
const platformLabels: Record<string, string> = {
  boss: "BOSS 直聘",
  manual: "手动导入",
  mock: "演示数据",
};

function descriptionSummary(title: string, description: string): string {
  const lines = description.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines.find((line) => (
    line !== title
    && !/^(Company|Location|Salary):/i.test(line)
    && !/^[#【\[]*(岗位职责|职位描述|任职要求|工作要求)[】\]：:\s#]*$/.test(line)
  )) ?? "查看完整职位描述";
}

export default function JobsPage() {
  const [search, setSearch] = useState("");
  const [jobs, setJobs] = useState<JobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawJd, setRawJd] = useState("");
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [page, setPage] = useState(1);
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
    setJobs(await getJobs({ search: search || undefined, page, page_size: PAGE_SIZE }));
  }

  useEffect(() => {
    setSelectedJobIds(new Set());
    const timer = window.setTimeout(() => {
      setLoading(true);
      getJobs({ search: search || undefined, page, page_size: PAGE_SIZE })
        .then(setJobs)
        .catch(() => setError("无法加载职位，请确认 API 服务已启动。"))
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [page, search]);

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
      const refreshed = await getJobs({ search: search || undefined, page, page_size: PAGE_SIZE });
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
      const refreshed = await getJobs({ search: search || undefined, page, page_size: PAGE_SIZE });
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

      <section className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <div className="panel self-start">
          <label className="block text-sm font-medium text-slate-700" htmlFor="job-search">
            搜索职位
          </label>
          <input
            id="job-search"
            className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
            onChange={(event) => { setSearch(event.target.value); setPage(1); }}
            placeholder="职位名称、描述或城市"
            value={search}
          />
        </div>
        <div className="panel">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="eyebrow">Job Intelligence</p>
              <h2 className="mt-2 text-xl font-semibold">导入与解析 JD</h2>
            </div>
            <button className="rounded-xl border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50" disabled={importing} onClick={() => void handleMockImport()} type="button">
              导入演示职位
            </button>
          </div>
          <textarea className="mt-4 min-h-28 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setRawJd(event.target.value)} placeholder="粘贴原始职位描述，系统会提取标题、技能、经验、学历与职责。" value={rawJd} />
          <button className="mt-3 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={importing} onClick={() => void handleImport()} type="button">
            {importing ? "处理中…" : "导入并解析"}
          </button>
        </div>
      </section>

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
        {jobs && jobs.items.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-6 py-3 text-sm">
          <label className="flex cursor-pointer items-center gap-2 text-slate-600">
            <input checked={jobs.items.every((job) => selectedJobIds.has(job.id))} className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" onChange={toggleCurrentPageSelection} type="checkbox" />
            <span>全选本页</span>
          </label>
          <div className="flex flex-wrap items-center gap-3">
            {selectedJobIds.size > 0 && <span className="text-slate-500">已选择 {selectedJobIds.size} 个职位</span>}
            {selectedJobIds.size > 0 && <button className="rounded-lg bg-rose-600 px-3 py-2 font-medium text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={bulkDeleting || saving} onClick={() => void handleDeleteSelected()} type="button">{bulkDeleting ? "删除中…" : "批量删除"}</button>}
            {selectedJobIds.size > 0 && <button className="rounded-lg border border-slate-200 px-3 py-2 text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700" disabled={bulkDeleting} onClick={() => setSelectedJobIds(new Set())} type="button">清空选择</button>}
          </div>
        </div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[780px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                <th className="w-12 px-6 py-4 font-medium"><span className="sr-only">选择</span></th>
                <th className="px-6 py-4 font-medium">职位</th>
                <th className="px-6 py-4 font-medium">平台</th>
                <th className="px-6 py-4 font-medium">地点</th>
                <th className="px-6 py-4 font-medium">薪资</th>
                <th className="px-6 py-4 font-medium">状态</th>
                <th className="px-6 py-4 font-medium">维护</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && <tr><td className="px-6 py-10 text-center text-slate-500" colSpan={7}>加载中…</td></tr>}
              {!loading && jobs?.items.length === 0 && <tr><td className="px-6 py-10 text-center text-slate-500" colSpan={7}>还没有职位数据。</td></tr>}
              {!loading && jobs?.items.map((job) => (
                <tr key={job.id} className="transition hover:bg-slate-50">
                  <td className="px-6 py-4 align-top"><input aria-label={`选择职位：${job.title}`} checked={selectedJobIds.has(job.id)} className="mt-1 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" onChange={() => toggleJobSelection(job.id)} type="checkbox" /></td>
                  <td className="px-6 py-4">
                    <Link className="font-semibold text-indigo-700 hover:text-indigo-900" href={`/jobs/${job.id}`}>
                      {job.title}
                    </Link>
                    <p className="mt-1 max-w-md truncate text-slate-500">{descriptionSummary(job.title, job.description)}</p>
                    {typeof job.raw_data.company_name === "string" && <p className="mt-1 text-xs text-slate-400">{job.raw_data.company_name}</p>}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-slate-600">{platformLabels[job.platform] ?? job.platform}</td>
                  <td className="px-6 py-4 text-slate-600">{job.location ?? "—"}</td>
                  <td className="whitespace-nowrap px-6 py-4 text-slate-600">
                    {typeof job.raw_data.salary_text === "string" ? job.raw_data.salary_text : job.salary_min || job.salary_max ? `${job.salary_min ?? "?"} - ${job.salary_max ?? "?"}` : "—"}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4"><span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">已采集</span></td>
                  <td className="whitespace-nowrap px-6 py-4"><div className="flex gap-2"><button className="text-sm font-medium text-indigo-700" disabled={bulkDeleting} onClick={() => beginEdit(job)} type="button">编辑</button><button className="text-sm font-medium text-rose-600" disabled={saving || bulkDeleting} onClick={() => void handleDeleteJob(job)} type="button">删除</button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {jobs && jobs.total > PAGE_SIZE && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-6 py-4 text-sm">
          <span className="text-slate-500">第 {jobs.page}/{Math.ceil(jobs.total / jobs.page_size)} 页 · 共 {jobs.total} 个职位</span>
          <div className="flex gap-2">
            <button className="rounded-lg border border-slate-200 px-3 py-2 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">上一页</button>
            <button className="rounded-lg border border-slate-200 px-3 py-2 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40" disabled={page >= Math.ceil(jobs.total / jobs.page_size) || loading} onClick={() => setPage((current) => current + 1)} type="button">下一页</button>
          </div>
        </div>}
      </section>
    </div>
  );
}
