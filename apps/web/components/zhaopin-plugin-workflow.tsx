"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createCuratedCampaign, getResumes, type Resume } from "../lib/api";
import { resolveZhaopinCityCode, zhaopinCityName, ZHAOPIN_CITY_OPTIONS } from "../lib/zhaopin-cities";

type CollectedJob = {
  id: string; external_job_id: string; title: string; location: string | null;
  company_name: string | null; salary_text: string | null; education: string | null;
  score?: number; score_status?: "SUFFICIENT" | "PARTIAL" | "INSUFFICIENT_DATA" | "FAILED";
  score_confidence?: number; score_error?: string;
};
type Task = {
  request_id: string; status: "RUNNING" | "WAITING_FOR_USER" | "INTERRUPTED" | "COMPLETED" | "FAILED" | "CANCELLED";
  search_url: string; target_count: number; resume_id?: string; quick_score_threshold: number;
  jobs: CollectedJob[]; created_count: number; updated_count: number;
  error?: string; end_reason?: string; active_url?: string; updated_at: string;
};
const STATUS: Record<Task["status"], string> = {
  RUNNING: "正在采集", WAITING_FOR_USER: "等待人工处理", INTERRUPTED: "可恢复", COMPLETED: "采集完成", FAILED: "已暂停，可重试", CANCELLED: "已停止",
};
const inputClass = "mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500 disabled:opacity-60";
const actionClass = "rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 disabled:opacity-50";

export function ZhaopinPluginWorkflow({ onCampaignCreated }: { onCampaignCreated?: () => Promise<unknown> | void }) {
  const [keyword, setKeyword] = useState("AI Agent RAG 实习");
  const [city, setCity] = useState("北京");
  const [searchOverride, setSearchOverride] = useState("");
  const [maxJobs, setMaxJobs] = useState(20);
  const [threshold, setThreshold] = useState(50);
  const [resumeId, setResumeId] = useState("");
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [task, setTask] = useState<Task | null>(null);
  const [connected, setConnected] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [choices, setChoices] = useState<Record<string, boolean>>({});
  const [creatingPlan, setCreatingPlan] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [createdPlan, setCreatedPlan] = useState<{ id: string; signature: string } | null>(null);
  const selectionRequest = useRef<string | null>(null);
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const expected = useRef<string | null>(null);
  const restored = useRef(false);
  const edited = useRef(false);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const busy = pending || task?.status === "RUNNING";
  const cityCode = resolveZhaopinCityCode(city);
  const searchUrl = searchOverride.trim() || (cityCode ? `https://www.zhaopin.com/sou?jl=${cityCode}&kw=${encodeURIComponent(keyword.trim())}` : "");

  useEffect(() => {
    let alive = true;
    getResumes().then((response) => {
      if (!alive) return;
      setResumes(response.items);
      setResumeId((current) => current || response.items.find((resume) => resume.is_default)?.id || response.items[0]?.id || "");
    }).catch(() => { if (alive) setError("无法读取简历，请检查后端连接"); });
    function receive(event: MessageEvent) {
      if (event.source !== window || event.data?.source !== "careerpilot-extension" || event.data.type !== "ZHAOPIN_TASK_STATE") return;
      const next = event.data.task as Task | null;
      setConnected(true);
      if (expected.current && next?.request_id !== expected.current) {
        if (event.data.request_id !== expected.current || !event.data.error) return;
      }
      if (timeout.current) clearTimeout(timeout.current);
      setPending(false);
      setError(event.data.error || null);
      if (!next) return;
      if (["CANCELLED", "COMPLETED", "FAILED", "INTERRUPTED"].includes(next.status)) {
        setStopping(false);
        setStopConfirmOpen(false);
      }
      expected.current = next.request_id;
      if (selectionRequest.current !== next.request_id) {
        selectionRequest.current = next.request_id;
        setCreatedPlan(null);
        setPlanError(null);
        try {
          const saved = JSON.parse(localStorage.getItem(`careerpilot:zhaopin-selection:${next.request_id}`) || "{}");
          setChoices(Object.fromEntries(Object.entries(saved).filter(([, value]) => typeof value === "boolean")) as Record<string, boolean>);
        } catch { setChoices({}); }
      }
      if (next.status !== "RUNNING") setNotice(null);
      setTask((current) => current?.updated_at === next.updated_at && current.status === next.status ? current : next);
      if (!restored.current) {
        restored.current = true;
        if (!edited.current) {
          const savedUrl = new URL(next.search_url);
          const plainQuery = savedUrl.pathname === "/sou" && [...savedUrl.searchParams.keys()].every((key) => ["jl", "kw"].includes(key));
          if (plainQuery && savedUrl.searchParams.get("jl")) {
            setKeyword(savedUrl.searchParams.get("kw") || "");
            setCity(zhaopinCityName(savedUrl.searchParams.get("jl")));
          } else {
            setSearchOverride(next.search_url);
          }
          setMaxJobs(next.target_count);
          setThreshold(next.quick_score_threshold);
          setResumeId(next.resume_id || "");
        }
      }
    }
    window.addEventListener("message", receive);
    const poll = () => window.postMessage({ source: "careerpilot-web", type: "ZHAOPIN_SEARCH_STATUS_REQUEST", request_id: crypto.randomUUID() }, window.location.origin);
    poll();
    const interval = setInterval(poll, 1500);
    return () => { alive = false; clearInterval(interval); if (timeout.current) clearTimeout(timeout.current); window.removeEventListener("message", receive); };
  }, []);

  function send(type: string, id: string, payload?: object) {
    expected.current = id;
    setPending(true); setError(null);
    if (timeout.current) clearTimeout(timeout.current);
    timeout.current = setTimeout(() => { setPending(false); setStopping(false); setStopConfirmOpen(false); setError("扩展未响应，请重新加载最新扩展并刷新本页后重试"); }, 10_000);
    window.postMessage({ source: "careerpilot-web", type, request_id: id, payload }, window.location.origin);
  }
  function start() {
    if (!keyword.trim()) { setError("请填写岗位关键词"); return; }
    if (!searchOverride.trim() && !cityCode) { setError("请输入城市名称或智联城市编码；未收录城市可粘贴智联搜索结果链接"); return; }
    restored.current = true; setNotice("正在请求扩展启动后台采集；连接成功后可离开本页，返回即可恢复进度。");
    send("ZHAOPIN_SEARCH_REQUEST", crypto.randomUUID(), {
      search_url: searchUrl, max_jobs: maxJobs, quick_score_threshold: threshold, resume_id: resumeId || undefined,
    });
  }
  const jobs = [...(task?.jobs ?? [])].sort((left, right) => {
    const group = (job: CollectedJob) => job.score === undefined ? 1 : job.score_status === "INSUFFICIENT_DATA" ? 1 : job.score < threshold ? 2 : 0;
    return group(left) - group(right) || (right.score ?? -1) - (left.score ?? -1);
  });
  const selected = (job: CollectedJob) => choices[job.id] ?? (job.score !== undefined && (job.score_status === "INSUFFICIENT_DATA" || job.score >= threshold));
  const count = jobs.filter(selected).length;
  const selectionSignature = JSON.stringify([task?.request_id, resumeId, jobs.filter(selected).map((job) => job.id).sort()]);
  const existingPlan = createdPlan?.signature === selectionSignature ? createdPlan : null;
  const low = jobs.filter((job) => job.score !== undefined && job.score_status !== "INSUFFICIENT_DATA" && job.score < threshold).length;
  const resumable = task && ["FAILED", "INTERRUPTED", "WAITING_FOR_USER"].includes(task.status);
  const canStop = task && ["RUNNING", "WAITING_FOR_USER", "INTERRUPTED"].includes(task.status);
  const progress = task ? Math.min(100, Math.round((jobs.length / Math.max(1, task.target_count)) * 100)) : 0;

  function stopCollection() {
    if (!task || !canStop) return;
    setStopping(true);
    setNotice("正在停止智联职位采集；已保存的岗位会保留，当前详情处理完成后停止。");
    send("ZHAOPIN_SEARCH_CANCEL_REQUEST", task.request_id);
  }

  function chooseJob(id: string, checked: boolean) {
    const next = { ...choices, [id]: checked };
    setChoices(next);
    try {
      if (task) localStorage.setItem(`careerpilot:zhaopin-selection:${task.request_id}`, JSON.stringify(next));
    } catch { setPlanError("浏览器无法保存勾选记录，刷新页面可能丢失选择；仍可直接创建计划。"); }
  }

  async function createSelectedPlan() {
    if (!task || !resumeId || !count || busy || creatingPlan || existingPlan) return;
    setCreatingPlan(true);
    setPlanError(null);
    try {
      const plan = await createCuratedCampaign({
        name: `智联 · ${keyword.trim() || "手选岗位"}`,
        query: keyword.trim(), resume_id: resumeId, job_ids: jobs.filter(selected).map((job) => job.id),
      });
      setCreatedPlan({ id: plan.id, signature: selectionSignature });
      // A refresh failure must not suggest that creating the persisted plan failed.
      try { await onCampaignCreated?.(); } catch { /* The detail link remains usable. */ }
    } catch (reason) {
      setPlanError(reason instanceof Error ? reason.message : "创建投递计划失败，请重试；已保留勾选结果。");
    } finally { setCreatingPlan(false); }
  }

  return <section className="panel overflow-hidden border-indigo-200">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="eyebrow">ZHAOPIN Extension Workflow</p>
        <h2 className="mt-2 text-xl font-semibold">按要求采集并保存完整岗位</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">扩展会在后台新建智联招聘标签页，自动翻页并逐个读取完整 JD、学历、经验、薪资和公司信息。每取得一个岗位就立即持久化并快速评分；登录、验证码、风控或平台限制会暂停等待人工处理。</p>
      </div>
      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${connected ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{connected ? "插件已连接" : "等待新版扩展连接"}</span>
    </div>

    <fieldset className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(180px,1fr)_140px_160px]" disabled={busy} onChange={() => { edited.current = true; }}>
      <label className="text-sm font-medium text-slate-700">岗位要求
        <input className={inputClass} maxLength={200} placeholder="例如：AI Agent、RAG、Python 实习" value={keyword} onChange={(e) => { setKeyword(e.target.value); setSearchOverride(""); }} />
      </label>
      <label className="text-sm font-medium text-slate-700" htmlFor="zhaopin-city">城市
        <input aria-describedby="zhaopin-city-help" className={inputClass} id="zhaopin-city" list="zhaopin-city-options" maxLength={30} placeholder="例如：北京、成都或 801" value={city} onChange={(e) => { setCity(e.target.value); setSearchOverride(""); }} />
        <datalist id="zhaopin-city-options">{ZHAOPIN_CITY_OPTIONS.map((item) => <option key={item.code} label={`智联编码 ${item.code}`} value={item.name} />)}</datalist>
      </label>
      <label className="text-sm font-medium text-slate-700">最多采集（1–200）
        <input className={inputClass} type="number" min={1} max={200} value={maxJobs} onChange={(e) => setMaxJobs(Math.min(200, Math.max(1, Math.floor(Number(e.target.value)) || 1)))} />
      </label>
      <label className="text-sm font-medium text-slate-700">快速评分阈值
        <input className={inputClass} type="number" min={0} max={100} value={threshold} onChange={(e) => setThreshold(Math.min(100, Math.max(0, Number(e.target.value) || 0)))} />
      </label>
    </fieldset>
    <details className="mt-4 text-sm text-slate-600">
      <summary className="cursor-pointer">使用智联上已筛选好的搜索链接</summary>
      <label className="mt-3 block">搜索结果页链接
        <input className={inputClass} disabled={busy} placeholder="https://www.zhaopin.com/sou/…" value={searchOverride} onChange={(e) => { edited.current = true; setSearchOverride(e.target.value); }} />
      </label>
      <p className="mt-2 text-xs text-slate-500">填写后优先使用此链接，保留智联网站上选择的城市、学历、经验等条件；也可直接输入城市名称或智联城市编码。</p>
    </details>
    {searchOverride && <p className="mt-2 text-sm text-indigo-700">已启用自定义搜索链接；修改关键词或城市可返回普通搜索。</p>}
    {!searchOverride && city.trim() && !cityCode && <p id="zhaopin-city-help" className="mt-2 text-sm text-amber-700">暂未识别“{city}”的智联编码，请改输入城市名/编码，或粘贴已筛选的智联搜索链接。</p>}

    <div className="mt-5 max-w-xl">
      <label className="text-sm font-medium text-slate-700">用于快速评分的简历
        <select className={inputClass} disabled={busy} value={resumeId} onChange={(e) => { edited.current = true; setResumeId(e.target.value); }}>
          <option value="">仅采集，暂不评分</option>{resumes.map((resume) => <option value={resume.id} key={resume.id}>{resume.name}{resume.is_default ? " · 默认" : ""}</option>)}
        </select>
      </label>
    </div>

    <div className="mt-5 flex flex-wrap items-center gap-3">
      <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" type="button" disabled={busy || !connected || task?.status === "WAITING_FOR_USER" || task?.status === "INTERRUPTED"} onClick={start}>{busy ? "插件采集中…" : resumable ? "放弃续采并重新检索" : jobs.length > 0 ? "重新检索智联" : "调动插件搜索智联"}</button>
      {searchUrl && <a className={actionClass} href={searchUrl} target="_blank" rel="noreferrer">预览搜索条件 ↗</a>}
      {canStop && <button className="rounded-xl border border-rose-300 bg-rose-50 px-5 py-3 text-sm font-medium text-rose-700 transition hover:border-rose-400 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50" disabled={pending || stopping} onClick={() => setStopConfirmOpen(true)} type="button">{stopping ? "正在停止…" : "停止采集"}</button>}
      {resumable && <button className="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={pending} onClick={() => send("ZHAOPIN_SEARCH_RESUME_REQUEST", task!.request_id)} type="button">继续采集</button>}
      {task?.active_url && <button className={actionClass} disabled={pending} onClick={() => send("ZHAOPIN_SEARCH_OPEN_REQUEST", task.request_id)} type="button">查看待处理智联页面 ↗</button>}
    </div>

    {!connected && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">请在浏览器扩展管理页重新加载 CareerPilot 扩展并刷新此页面。新版支持智联完整详情、自动翻页和断点继续。</p>}
    {notice && <p className="mt-4 rounded-xl bg-indigo-50 p-4 text-sm leading-6 text-indigo-700">{notice}</p>}
    {error && <p role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm leading-6 text-rose-800">{error}</p>}

    {task && <div className="mt-6 space-y-4">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex justify-between gap-3 text-sm"><span className="font-semibold">{STATUS[task.status]}</span><span>已保存完整 JD {jobs.length}/{task.target_count}</span></div>
        <progress className="mt-3 h-2 w-full accent-indigo-600" aria-label="智联职位采集进度" max={task.target_count} value={jobs.length} />
        <p className="mt-2 text-xs text-slate-500">新增 {task.created_count} · 更新 {task.updated_count} · 已评分 {jobs.filter((job) => job.score !== undefined).length} · 进度 {progress}%</p>
        {task.error && <p role="alert" className="mt-3 text-sm text-amber-800">{task.error}</p>}
        {task.status === "WAITING_FOR_USER" && <p className="mt-2 text-sm text-slate-600">请在扩展已打开的智联采集标签页处理提示，再点击“继续采集”。已完成岗位会保留。</p>}
        {task.end_reason && <p className="mt-2 text-sm text-slate-500">{task.end_reason}</p>}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Imported Jobs</p><h3 className="mt-2 font-semibold">确认本次采集岗位</h3></div><span className="text-sm text-slate-500">已选 {count}/{jobs.length} · 低于阈值 {low} 个</span></div>
      <div className="divide-y divide-slate-100 rounded-2xl border border-slate-200">
        {jobs.map((job) => {
          const insufficient = job.score_status === "INSUFFICIENT_DATA";
          const lowScore = job.score !== undefined && !insufficient && job.score < threshold;
          return <label className={`flex cursor-pointer items-start gap-4 p-4 ${lowScore ? "cp-low-match-surface" : ""}`} key={job.id}>
            <input aria-label={`选择${job.title}`} checked={selected(job)} disabled={creatingPlan} className="mt-1 h-4 w-4 accent-indigo-600" onChange={(e) => chooseJob(job.id, e.target.checked)} type="checkbox" />
            <span className="min-w-0 flex-1"><span className="font-medium">{job.title}</span><span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">完整 JD</span>{job.score !== undefined && <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${insufficient ? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" : lowScore ? "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200" : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-200"}`} title="匹配分表示岗位符合程度；置信度表示系统对该结果的可靠程度">{insufficient ? "JD 信息不足" : `快速评分 ${Math.round(job.score)}`}{job.score_confidence !== undefined ? ` · 置信度 ${Math.round(job.score_confidence * 100)}%` : ""}</span>}<span className="mt-1 block text-sm text-slate-500 dark:text-slate-400">{job.company_name || "公司待补充"} · {job.location || "地点待补充"} · {job.salary_text || "薪资未公开"} · {job.education || "学历未注明"}</span>{insufficient && <span className="mt-2 block text-sm text-slate-600 dark:text-slate-300">职位描述不足，暂不按低匹配处理，请人工确认。</span>}{lowScore && <span className="mt-2 block text-sm font-medium text-amber-800 dark:text-amber-200">与当前简历符合度不高，已默认不勾选并置后；如仍要保留，请手动勾选。</span>}{job.score_error && <span className="mt-2 block text-sm text-amber-800 dark:text-amber-200">{job.score_error}</span>}{job.score === undefined && !job.score_error && task.resume_id && task.status === "RUNNING" && <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">快速评分中…</span>}</span>
            <Link className="shrink-0 text-sm font-medium text-indigo-700" href={`/jobs/${job.id}`} onClick={(event) => event.stopPropagation()}>本地详情</Link>
          </label>;
        })}
      </div>
      <p className="text-xs leading-5 text-slate-500">岗位已入库，手动勾选按本次采集任务保存在当前浏览器。快速评分对应采集时选择的简历，更换简历不会重新计算已有评分。创建计划只保存所选岗位；批准岗位后可在下方一键投递，实际使用智联账号中已设置的简历。</p>
      <div className="flex flex-wrap items-center gap-3">
        <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:opacity-50" disabled={busy || creatingPlan || !resumeId || count === 0 || !!existingPlan} onClick={() => void createSelectedPlan()} type="button">{creatingPlan ? "正在保存计划…" : existingPlan ? "已创建投递计划" : `用所选 ${count} 个岗位创建计划`}</button>
        {!resumeId && <span className="text-sm text-amber-800">请先在上方选择用于投递计划的简历。</span>}
        {existingPlan && <Link className="text-sm font-medium text-indigo-700" href={`/campaigns/${existingPlan.id}`}>查看投递计划并确认 →</Link>}
      </div>
      {planError && <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{planError}</p>}
    </div>}

    {stopConfirmOpen && <div aria-labelledby="stop-zhaopin-collection-title" aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4" role="dialog">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
        <p className="eyebrow">停止职位采集</p>
        <h3 className="mt-2 text-lg font-semibold" id="stop-zhaopin-collection-title">确定停止当前采集任务？</h3>
        <p className="mt-3 text-sm leading-6 text-slate-500">扩展将停止读取新岗位和翻页。已经持久化的 {task?.jobs.length ?? 0} 个岗位会保留，之后仍可筛选、评分和查看详情。</p>
        <div className="mt-6 flex justify-end gap-3"><button className={actionClass} disabled={stopping} onClick={() => setStopConfirmOpen(false)} type="button">继续采集</button><button className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-rose-700 disabled:opacity-50" disabled={stopping} onClick={stopCollection} type="button">{stopping ? "正在停止…" : "确认停止"}</button></div>
      </div>
    </div>}
  </section>;
}
