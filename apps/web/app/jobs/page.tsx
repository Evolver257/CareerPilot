"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getJobs, type JobListResponse } from "../../lib/api";
import { importJobs } from "../../lib/api";

export default function JobsPage() {
  const [search, setSearch] = useState("");
  const [jobs, setJobs] = useState<JobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawJd, setRawJd] = useState("");
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      getJobs(search || undefined)
        .then(setJobs)
        .catch(() => setError("无法加载职位，请确认 API 服务已启动。"))
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

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
      const refreshed = await getJobs(search || undefined);
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
      const refreshed = await getJobs(search || undefined);
      setJobs(refreshed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Mock 职位导入失败。");
    } finally {
      setImporting(false);
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
        <div className="panel">
          <label className="block text-sm font-medium text-slate-700" htmlFor="job-search">
            搜索职位
          </label>
          <input
            id="job-search"
            className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
            onChange={(event) => setSearch(event.target.value)}
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
              导入 30 条 Mock JD
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

      <section className="panel overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                <th className="px-6 py-4 font-medium">职位</th>
                <th className="px-6 py-4 font-medium">平台</th>
                <th className="px-6 py-4 font-medium">地点</th>
                <th className="px-6 py-4 font-medium">薪资</th>
                <th className="px-6 py-4 font-medium">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && <tr><td className="px-6 py-10 text-center text-slate-500" colSpan={5}>加载中…</td></tr>}
              {!loading && jobs?.items.length === 0 && <tr><td className="px-6 py-10 text-center text-slate-500" colSpan={5}>还没有职位数据。</td></tr>}
              {!loading && jobs?.items.map((job) => (
                <tr key={job.id} className="transition hover:bg-slate-50">
                  <td className="px-6 py-4">
                    <Link className="font-semibold text-indigo-700 hover:text-indigo-900" href={`/jobs/${job.id}`}>
                      {job.title}
                    </Link>
                    <p className="mt-1 max-w-md truncate text-slate-500">{job.description}</p>
                  </td>
                  <td className="px-6 py-4 text-slate-600">{job.platform}</td>
                  <td className="px-6 py-4 text-slate-600">{job.location ?? "—"}</td>
                  <td className="px-6 py-4 text-slate-600">
                    {job.salary_min || job.salary_max ? `${job.salary_min ?? "?"} - ${job.salary_max ?? "?"}` : "—"}
                  </td>
                  <td className="px-6 py-4"><span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">DISCOVERED</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
