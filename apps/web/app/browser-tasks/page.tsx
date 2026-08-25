"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  createBrowserTask,
  getApplications,
  getBrowserTasks,
  type ApplicationListItem,
  type BrowserTask,
} from "../../lib/api";

const statusLabels: Record<BrowserTask["status"], string> = {
  PENDING: "待启动",
  CONNECTING: "等待 Extension",
  RUNNING: "执行中",
  WAITING_FOR_USER: "等待人工处理",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
};

export default function BrowserTasksPage() {
  const [tasks, setTasks] = useState<BrowserTask[]>([]);
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [applicationId, setApplicationId] = useState("");
  const [platform, setPlatform] = useState<"mock" | "careerboard">("mock");
  const [scenario, setScenario] = useState("SUCCESS");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    return Promise.all([getBrowserTasks(), getApplications()]).then(([taskResponse, applicationResponse]) => {
      setTasks(taskResponse.items);
      setApplications(applicationResponse.items.filter((item) => item.status === "QUEUED"));
      setApplicationId((current) => {
        const next = current || applicationResponse.items.find((item) => item.status === "QUEUED")?.id || "";
        const selected = applicationResponse.items.find((item) => item.id === next);
        if (selected?.platform === "careerboard") setPlatform("careerboard");
        return next;
      });
    });
  }

  useEffect(() => {
    load().catch(() => setError("无法加载 Browser Task 数据，请确认 API 服务已启动。")).finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!applicationId) return;
    setCreating(true);
    setError(null);
    try {
      await createBrowserTask({ application_id: applicationId, platform, scenario, auto_start: true });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Browser Task 创建失败。");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">Browser Agent</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Browser Tasks</h1>
        <p className="mt-3 max-w-3xl text-slate-500">把已批准的 Application 交给 Platform Adapter，再由 Browser Extension 在 Mock Job Site 执行结构化动作。</p>
      </header>
      <section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">New Task</p><h2 className="mt-2 text-xl font-semibold">启动平台 Adapter 投递</h2></div><Link className="text-sm font-medium text-indigo-700" href="/mock-platform">打开本地 Job Site →</Link></div>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">已排队 Application<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => { const nextId = event.target.value; setApplicationId(nextId); const selected = applications.find((item) => item.id === nextId); setPlatform(selected?.platform === "careerboard" ? "careerboard" : "mock"); }} value={applicationId}><option value="">请选择 Application</option>{applications.map((item) => <option key={item.id} value={item.id}>{item.job.title} · {item.platform} · {item.id.slice(0, 8)}</option>)}</select></label>
          <label className="text-sm font-medium text-slate-700">Platform Adapter<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setPlatform(event.target.value as "mock" | "careerboard")} value={platform}><option value="mock">Mock Platform · 本地 Fixture</option><option value="careerboard">CareerBoard Prototype · 用户浏览器</option></select></label>
          <label className="text-sm font-medium text-slate-700">Adapter 场景<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setScenario(event.target.value)} value={scenario}><option value="SUCCESS">SUCCESS · 正常投递</option><option value="CAPTCHA_REQUIRED">CAPTCHA_REQUIRED · 需要人工处理</option><option value="LOGIN_REQUIRED">LOGIN_REQUIRED · 需要登录</option><option value="RISK_CONTROL">RISK_CONTROL · 风控暂停</option><option value="UNKNOWN_STATE">UNKNOWN_STATE · 未知 DOM 暂停</option><option value="PLATFORM_LIMIT">PLATFORM_LIMIT · 平台限制</option><option value="DOM_CHANGED">DOM_CHANGED · DOM 变化</option></select></label>
        </div>
        {platform === "careerboard" && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">CareerBoard 目前是安全原型：只允许用户主动打开的浏览器 Session，不上传密码、Cookie 或 Token；验证码、登录、风控和未知页面会立即暂停。</p>}
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={creating || !applicationId} onClick={() => void handleCreate()} type="button">{creating ? "创建中…" : "创建 Browser Task"}</button>
        {applications.length === 0 && <p className="mt-4 text-sm text-slate-500">暂无 QUEUED Application。请先在 Agent Trace 审批候选职位。</p>}
      </section>
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      <section>
        <div className="mb-4 flex items-end justify-between"><div><p className="eyebrow">Task History</p><h2 className="mt-2 text-xl font-semibold">任务记录</h2></div><span className="text-sm text-slate-500">{tasks.length} tasks</span></div>
        {loading && <div className="panel text-center text-slate-500">加载中…</div>}
        {!loading && tasks.length === 0 && <div className="panel text-center text-slate-500">还没有 Browser Task。</div>}
        <div className="grid gap-4 lg:grid-cols-2">{tasks.map((task) => <Link className="panel block transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md" href={`/browser-tasks/${task.id}`} key={task.id}><div className="flex items-start justify-between gap-4"><div><h3 className="font-semibold">{task.platform} Application · {task.application_id.slice(0, 8)}</h3><p className="mt-2 text-xs text-slate-500">{task.scenario} · {task.action_sequence} actions</p></div><span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[task.status]}</span></div><div className="mt-5 flex justify-between border-t border-slate-100 pt-4 text-sm text-slate-500"><span>{task.events.length} events</span><span>{new Date(task.created_at).toLocaleString("zh-CN")}</span></div></Link>)}</div>
      </section>
    </div>
  );
}
