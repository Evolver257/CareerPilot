"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  approveCampaignJobs,
  createCampaignBrowserTasks,
  createCuratedCampaign,
  getResumes,
  importBossVisibleJobs,
  type BossVisibleJobCapture,
  type BrowserTask,
  type Job,
  type Resume,
} from "../lib/api";

type ExtensionStatus = "checking" | "connected" | "missing";
type WorkflowStage = "idle" | "searching" | "importing" | "preparing" | "ready";

type BossExtensionMessage = {
  source: "careerpilot-extension";
  type: "BOSS_EXTENSION_PONG" | "BOSS_SEARCH_RESULT" | "BOSS_TASK_LAUNCH_RESULT" | "BOSS_TASK_BATCH_LAUNCH_RESULT";
  request_id: string;
  success?: boolean;
  version?: string;
  page_url?: string;
  page_state?: string;
  jobs?: BossVisibleJobCapture[];
  error?: string;
};

type CaptureResult = Required<Pick<BossExtensionMessage, "page_url" | "jobs">> &
  Pick<BossExtensionMessage, "success" | "page_state" | "error">;

const MAX_VISIBLE_BOSS_JOBS = 50;

export function BossPluginWorkflow({ onTasksCreated }: { onTasksCreated: () => Promise<void> }) {
  const [extensionStatus, setExtensionStatus] = useState<ExtensionStatus>("checking");
  const [extensionVersion, setExtensionVersion] = useState("");
  const [stage, setStage] = useState<WorkflowStage>("idle");
  const [requirements, setRequirements] = useState("AI Agent RAG 实习");
  const [city, setCity] = useState("北京");
  const [maxJobs, setMaxJobs] = useState(10);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [tasks, setTasks] = useState<BrowserTask[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeSearchRequest = useRef<string | null>(null);
  const searchTimeout = useRef<number | null>(null);

  const processCapture = useCallback(async (result: CaptureResult) => {
    if (!result.success) {
      setStage("idle");
      setError(result.error || `BOSS 页面状态为 ${result.page_state ?? "UNKNOWN_STATE"}，请人工处理后重试。`);
      return;
    }
    if (!result.page_url || result.jobs.length === 0) {
      setStage("idle");
      setError("扩展没有在当前可见页面识别到职位卡片。请确认 BOSS 搜索结果已正常显示。");
      return;
    }
    setStage("importing");
    try {
      const imported = await importBossVisibleJobs({ page_url: result.page_url, jobs: result.jobs });
      setJobs(imported.items);
      setSelectedJobIds(imported.items.filter((job) => job.raw_data.description_source === "detail_panel").map((job) => job.id));
      const detailed = imported.items.filter((job) => job.raw_data.description_source === "detail_panel").length;
      setNotice(`采集并持久化完成：新增 ${imported.created} 条，更新完整 JD ${imported.updated} 条；本次 ${detailed}/${imported.total} 条已获取完整 JD。`);
      setStage("ready");
    } catch (reason) {
      setStage("idle");
      setError(reason instanceof Error ? reason.message : "BOSS 职位导入失败。");
    }
  }, []);

  useEffect(() => {
    getResumes().then((response) => {
      setResumes(response.items);
      setResumeId(response.items.find((resume) => resume.is_default)?.id ?? response.items[0]?.id ?? "");
    }).catch(() => setError("无法读取简历，请确认 API 服务已启动。"));
  }, []);

  useEffect(() => {
    function receiveExtensionMessage(event: MessageEvent<unknown>) {
      if (event.source !== window || !isExtensionMessage(event.data)) return;
      const message = event.data;
      if (message.type === "BOSS_EXTENSION_PONG") {
        setExtensionStatus("connected");
        setExtensionVersion(message.version ?? "dev");
        return;
      }
      if (message.type !== "BOSS_SEARCH_RESULT" || message.request_id !== activeSearchRequest.current) return;
      activeSearchRequest.current = null;
      if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
      void processCapture({
        success: message.success,
        page_url: message.page_url ?? "",
        jobs: message.jobs ?? [],
        page_state: message.page_state,
        error: message.error,
      });
    }

    window.addEventListener("message", receiveExtensionMessage);
    const pingRequestId = window.crypto.randomUUID();
    window.postMessage({
      source: "careerpilot-web",
      type: "BOSS_EXTENSION_PING",
      request_id: pingRequestId,
    }, window.location.origin);
    const pingTimeout = window.setTimeout(() => {
      setExtensionStatus((current) => current === "checking" ? "missing" : current);
    }, 1200);
    return () => {
      window.removeEventListener("message", receiveExtensionMessage);
      window.clearTimeout(pingTimeout);
      if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
    };
  }, [processCapture]);

  function startSearch() {
    if (!requirements.trim() || extensionStatus !== "connected") return;
    const requestId = window.crypto.randomUUID();
    const requestedMaxJobs = Math.min(Math.max(maxJobs, 1), MAX_VISIBLE_BOSS_JOBS);
    activeSearchRequest.current = requestId;
    setStage("searching");
    setJobs([]);
    setTasks([]);
    setError(null);
    setNotice("扩展正在打开 BOSS 搜索页并读取当前可见职位；如需登录，请在打开的标签页中人工完成。");
    window.postMessage({
      source: "careerpilot-web",
      type: "BOSS_SEARCH_REQUEST",
      request_id: requestId,
      payload: {
        requirements: requirements.trim(),
        city: city.trim(),
        max_jobs: requestedMaxJobs,
      },
    }, window.location.origin);
    const collectionTimeoutMs = Math.min(240_000, Math.max(45_000, requestedMaxJobs * 3_000 + 20_000));
    searchTimeout.current = window.setTimeout(() => {
      if (activeSearchRequest.current !== requestId) return;
      activeSearchRequest.current = null;
      setStage("idle");
      setError("扩展响应超时。请检查扩展是否已重新加载，以及 BOSS 页面是否需要人工登录或验证。");
    }, collectionTimeoutMs);
  }

  async function approveAndLaunch() {
    if (!resumeId || selectedJobIds.length === 0 || !confirmed) return;
    setStage("preparing");
    setError(null);
    setNotice("正在创建精确候选 Campaign、记录用户批准并生成 Browser Tasks…");
    try {
      const campaign = await createCuratedCampaign({
        name: `BOSS · ${requirements.trim().slice(0, 60)}`,
        resume_id: resumeId,
        job_ids: selectedJobIds,
        query: [requirements.trim(), city.trim()].filter(Boolean).join(" · "),
      });
      await approveCampaignJobs(campaign.id, selectedJobIds);
      const batch = await createCampaignBrowserTasks({
        campaign_id: campaign.id,
        platform: "boss",
        scenario: "SUCCESS",
        auto_start: true,
      });
      const createdTasks: BrowserTask[] = batch.items;
      const launchTasks = createdTasks.flatMap((task) => {
        const url = getTaskLaunchUrl(task);
        return url ? [{ task_id: task.id, url }] : [];
      });
      if (launchTasks.length > 0) {
        window.postMessage({
          source: "careerpilot-web",
          type: "BOSS_TASK_BATCH_LAUNCH_REQUEST",
          request_id: window.crypto.randomUUID(),
          tasks: launchTasks,
        }, window.location.origin);
      }
      setTasks(createdTasks);
      setNotice(`已批准 ${createdTasks.length} 个 BOSS Browser Task，并加入单标签页串行投递队列。页面异常会暂停在当前岗位等待人工处理。`);
      setStage("ready");
      await onTasksCreated();
    } catch (reason) {
      setStage("ready");
      setError(reason instanceof Error ? reason.message : "BOSS 投递任务创建失败。");
    }
  }

  const busy = stage === "searching" || stage === "importing" || stage === "preparing";

  return (
    <section className="panel overflow-hidden border-indigo-200">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">BOSS Extension Workflow</p>
          <h2 className="mt-2 text-xl font-semibold">按要求采集并对接投递</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">在这里发送搜索条件给本地扩展。扩展只打开用户可见的 BOSS 页面并提取当前结果，导入后由你勾选、批准，再创建投递任务。</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${extensionStatus === "connected" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
          {extensionStatus === "connected" ? `插件已连接 ${extensionVersion}` : extensionStatus === "checking" ? "正在检测插件" : "未检测到插件"}
        </span>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(180px,1fr)_140px]">
        <label className="text-sm font-medium text-slate-700">岗位要求
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" maxLength={200} onChange={(event) => setRequirements(event.target.value)} placeholder="例如：AI Agent、RAG、Python 实习" value={requirements} />
        </label>
        <label className="text-sm font-medium text-slate-700">城市
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" maxLength={30} onChange={(event) => setCity(event.target.value)} placeholder="北京" value={city} />
        </label>
        <label className="text-sm font-medium text-slate-700">最多采集（1–50）
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" max={MAX_VISIBLE_BOSS_JOBS} min={1} onChange={(event) => setMaxJobs(Number(event.target.value) || 1)} type="number" value={maxJobs} />
        </label>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || extensionStatus !== "connected" || !requirements.trim()} onClick={startSearch} type="button">
          {stage === "searching" || stage === "importing" ? "插件采集中…" : "调动插件搜索 BOSS"}
        </button>
        <a className="text-sm font-medium text-indigo-700" href="https://www.zhipin.com/web/geek/jobs" rel="noreferrer" target="_blank">手动打开 BOSS →</a>
      </div>

      {extensionStatus === "missing" && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">请在浏览器扩展管理页加载或重新加载 <code>apps/extension/.output/chrome-mv3</code>，然后刷新此页面。插件连接只在本机浏览器内建立。</p>}
      {notice && <p className="mt-4 rounded-xl bg-indigo-50 p-4 text-sm leading-6 text-indigo-700">{notice}</p>}
      {error && <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm leading-6 text-rose-800">{error}</p>}

      {jobs.length > 0 && <div className="mt-7 space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Imported Jobs</p><h3 className="mt-2 font-semibold">选择需要投递的职位</h3></div><span className="text-sm text-slate-500">已选 {selectedJobIds.length}/{jobs.length}</span></div>
        <div className="divide-y divide-slate-100 rounded-2xl border border-slate-200">
          {jobs.map((job) => {
            const checked = selectedJobIds.includes(job.id);
            const company = typeof job.raw_data.company_name === "string" ? job.raw_data.company_name : "公司待补充";
            const salary = typeof job.raw_data.salary_text === "string" ? job.raw_data.salary_text : "薪资面议";
            const hasFullJd = job.raw_data.description_source === "detail_panel";
            return <label className="flex cursor-pointer items-start gap-4 p-4" key={job.id}>
              <input checked={checked} className="mt-1 h-4 w-4 accent-indigo-600" onChange={() => setSelectedJobIds((current) => checked ? current.filter((id) => id !== job.id) : [...current, job.id])} type="checkbox" />
              <span className="min-w-0 flex-1"><span className="font-medium">{job.title}</span><span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{hasFullJd ? "完整 JD" : "卡片摘要"}</span><span className="mt-1 block text-sm text-slate-500">{company} · {job.location ?? "地点待补充"} · {salary}</span></span>
              <Link className="text-sm font-medium text-indigo-700" href={`/jobs/${job.id}`} onClick={(event) => event.stopPropagation()}>本地详情</Link>
            </label>;
          })}
        </div>

        <div className="grid gap-4 border-t border-slate-100 pt-5 lg:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">投递简历
            <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setResumeId(event.target.value)} value={resumeId}>
              <option value="">请选择简历</option>
              {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.name}{resume.is_default ? " · 默认" : ""}</option>)}
            </select>
          </label>
          <label className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">
            <input checked={confirmed} className="mt-1 h-4 w-4 accent-indigo-600" onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" />
            <span>我确认对已勾选岗位创建并启动投递任务；如出现登录、验证码、风控或未知页面，任务必须暂停等待我处理。</span>
          </label>
        </div>
        {resumes.length === 0 && <p className="text-sm text-amber-700">还没有可用简历，请先前往 <Link className="font-medium underline" href="/resume">简历管理</Link> 上传并解析。</p>}
        <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || selectedJobIds.length === 0 || !resumeId || !confirmed || extensionStatus !== "connected"} onClick={() => void approveAndLaunch()} type="button">
          {stage === "preparing" ? "正在创建投递任务…" : `批准并启动 ${selectedJobIds.length} 个投递任务`}
        </button>
      </div>}

      {tasks.length > 0 && <div className="mt-6 flex flex-wrap gap-3">{tasks.map((task) => <Link className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-indigo-700" href={`/browser-tasks/${task.id}`} key={task.id}>查看 Task {task.id.slice(0, 8)} →</Link>)}</div>}
    </section>
  );
}

function isExtensionMessage(value: unknown): value is BossExtensionMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as Partial<BossExtensionMessage>;
  return message.source === "careerpilot-extension" && typeof message.type === "string" && typeof message.request_id === "string";
}

function getTaskLaunchUrl(task: BrowserTask): string | null {
  const actions = task.payload.actions;
  if (!Array.isArray(actions)) return null;
  const first = actions[0];
  if (!first || typeof first !== "object") return null;
  const url = (first as { url?: unknown }).url;
  return typeof url === "string" ? url : null;
}
