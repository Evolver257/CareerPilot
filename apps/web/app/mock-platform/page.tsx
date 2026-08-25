"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getJobs, type Job } from "../../lib/api";

export default function MockPlatformPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJobs()
      .then((response) => setJobs(response.items))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "职位加载失败。"));
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="rounded-2xl border border-indigo-200 bg-indigo-950 p-8 text-white shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-300">Mock Job Site</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">CareerBoard Mock Platform</h1>
        <p className="mt-3 max-w-3xl text-indigo-100">本地招聘网站模拟页，供 Browser Extension 执行 NAVIGATE、CHECK_STATE、CLICK 和 EXTRACT。</p>
      </header>
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      <section>
        <div className="mb-4 flex items-end justify-between"><div><p className="eyebrow">Job Listings</p><h2 className="mt-2 text-xl font-semibold">职位列表</h2></div><span className="text-sm text-slate-500">{jobs.length} jobs</span></div>
        <div className="grid gap-4 lg:grid-cols-2">
          {jobs.map((job) => <Link className="panel transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md" href={`/mock-platform/jobs/${job.id}`} key={job.id}><div className="flex items-start justify-between gap-4"><div><h3 className="font-semibold text-slate-900">{job.title}</h3><p className="mt-2 text-sm text-slate-500">{job.location ?? "地点未注明"} · {job.platform}</p></div><span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">可投递</span></div><p className="mt-4 line-clamp-2 text-sm leading-6 text-slate-500">{job.description}</p></Link>)}
        </div>
      </section>
    </div>
  );
}
