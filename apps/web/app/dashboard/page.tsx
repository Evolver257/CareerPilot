"use client";

import { useEffect, useState } from "react";

import { StatCard } from "../../components/stat-card";
import { getApplications, getJobs, type ApplicationListResponse, type JobListResponse } from "../../lib/api";

export default function DashboardPage() {
  const [jobs, setJobs] = useState<JobListResponse | null>(null);
  const [applications, setApplications] = useState<ApplicationListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getJobs(), getApplications()])
      .then(([jobResponse, applicationResponse]) => {
        setJobs(jobResponse);
        setApplications(applicationResponse);
      })
      .catch(() => setError("API 暂不可用，请确认 FastAPI 已启动。"));
  }, []);

  const waiting = applications?.items.filter((item) => item.status === "WAITING_APPROVAL").length ?? 0;
  const queued = applications?.items.filter((item) => ["QUEUED", "EXECUTING", "PAUSED"].includes(item.status)).length ?? 0;
  const submitted = applications?.items.filter((item) => item.status === "SUBMITTED").length ?? 0;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <p className="eyebrow">CareerPilot / Foundation</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">求职工作台</h1>
        <p className="mt-3 max-w-2xl text-slate-500">
          从职位发现开始，逐步连接简历、匹配、Campaign 和人工确认流程。
        </p>
      </header>

      {error && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800">{error}</div>}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="发现职位" value={jobs?.total ?? "—"} hint="来自 API 的实时数量" />
        <StatCard label="高匹配职位" value="—" hint="Phase 5 Ranking 已启用" />
        <StatCard label="等待确认" value={waiting} hint="Human-in-the-loop" />
        <StatCard label="已排队 / 投递" value={queued + " / " + submitted} hint="Campaign State Machine" />
      </section>

      <section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Pipeline</p>
            <h2 className="mt-2 text-xl font-semibold">求职漏斗</h2>
          </div>
          <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700">Foundation</span>
        </div>
        <div className="mt-8 grid gap-3 sm:grid-cols-5">
          {["Discovered", "Qualified", "Queued", "Applied", "Interview"].map((stage, index) => (
            <div key={stage} className="rounded-xl bg-slate-50 p-4">
              <p className="text-sm text-slate-500">0{index + 1}</p>
              <p className="mt-4 font-medium">{stage}</p>
              <p className="mt-1 text-2xl font-semibold">{index === 0 ? jobs?.total ?? "—" : index === 1 ? applications?.total ?? 0 : index === 2 ? queued : index === 3 ? submitted : "—"}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
