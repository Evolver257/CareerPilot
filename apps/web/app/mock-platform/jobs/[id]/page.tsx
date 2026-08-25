"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getJob, type Job } from "../../../../lib/api";

export default function MockJobDetailPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const [job, setJob] = useState<Job | null>(null);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJob(params.id).then(setJob).catch((reason) => setError(reason instanceof Error ? reason.message : "职位加载失败。"));
  }, [params.id]);

  if (!job) return <div className="panel mx-auto max-w-4xl text-slate-500">{error ?? "加载 Mock 职位…"}</div>;
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link className="text-sm font-medium text-indigo-700" href="/mock-platform">← 返回职位列表</Link>
      <article className="panel border-indigo-200" data-cp-page="job-detail">
        <div className="flex flex-wrap items-start justify-between gap-5"><div><p className="eyebrow">CareerBoard · Mock Detail</p><h1 className="mt-3 text-3xl font-semibold" data-cp-field="job-title">{job.title}</h1><p className="mt-3 text-slate-500" data-cp-field="location">{job.location ?? "地点未注明"} · {job.platform}</p></div><span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">职位详情</span></div>
        <div className="mt-8 whitespace-pre-wrap border-t border-slate-100 pt-6 text-sm leading-7 text-slate-600" data-cp-field="description">{job.description}</div>
        <div className="mt-8 rounded-xl bg-slate-50 p-4 text-xs text-slate-500"><p>Task: {searchParams.get("task") ?? "manual-preview"}</p><p className="mt-1">页面状态: {applied ? "APPLICATION_SUBMITTED" : "READY_TO_APPLY"}</p></div>
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white hover:bg-indigo-700" data-cp-action="apply" data-mock-action="apply" onClick={() => setApplied(true)} type="button">{applied ? "已投递" : "立即投递"}</button>
      </article>
    </div>
  );
}
