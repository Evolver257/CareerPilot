"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  approveCampaignJobs,
  createCampaignBrowserTasks,
  createCuratedCampaign,
  getResumes,
  importBossVisibleJobs,
  quickScoreJobs,
  type BossVisibleJobCapture,
  type BrowserTask,
  type Job,
  type QuickJobScore,
  type Resume,
} from "../lib/api";

type ExtensionStatus = "checking" | "connected" | "missing";
type WorkflowStage = "idle" | "searching" | "importing" | "preparing" | "ready";

type BossExtensionMessage = {
  source: "careerpilot-extension";
  type: "BOSS_EXTENSION_PONG" | "BOSS_SEARCH_PROGRESS" | "BOSS_SEARCH_RESULT" | "BOSS_SEARCH_STATUS_RESULT" | "BOSS_TASK_LAUNCH_RESULT" | "BOSS_TASK_BATCH_LAUNCH_RESULT";
  request_id: string;
  success?: boolean;
  version?: string;
  page_url?: string;
  page_state?: string;
  jobs?: BossVisibleJobCapture[];
  collected_count?: number;
  target_count?: number;
  task?: BossBackgroundSearchTask | null;
  background_task?: BossBackgroundSearchTask;
  error?: string;
};

type BossPersistedJobSummary = {
  id: string;
  external_job_id: string | null;
  title: string;
  location: string | null;
  company_name: string | null;
  salary_text: string | null;
  description_source: "detail_panel" | "card_summary";
};

type BossBackgroundSearchTask = {
  request_id: string;
  status: "RUNNING" | "WAITING_FOR_USER" | "COMPLETED" | "FAILED";
  requirements: string;
  city: string;
  target_count: number;
  quick_score_threshold?: number;
  collected_count: number;
  persisted_count: number;
  created_count: number;
  updated_count: number;
  detailed_count: number;
  page_url: string;
  tab_id?: number;
  page_state: string;
  persisted_jobs: BossPersistedJobSummary[];
  error?: string;
  started_at: string;
  updated_at: string;
  finished_at?: string;
};

type CaptureResult = Required<Pick<BossExtensionMessage, "page_url" | "jobs">> &
  Pick<BossExtensionMessage, "success" | "page_state" | "error">;

const MAX_VISIBLE_BOSS_JOBS = 200;
const COLLECTION_INACTIVITY_TIMEOUT_MS = 90_000;
const DEFAULT_QUICK_SCORE_THRESHOLD = 50;

export function BossPluginWorkflow({ onTasksCreated }: { onTasksCreated: () => Promise<void> }) {
  const [extensionStatus, setExtensionStatus] = useState<ExtensionStatus>("checking");
  const [extensionVersion, setExtensionVersion] = useState("");
  const [stage, setStage] = useState<WorkflowStage>("idle");
  const [requirements, setRequirements] = useState("AI Agent RAG 实习");
  const [city, setCity] = useState("北京");
  const [maxJobs, setMaxJobs] = useState(10);
  const [quickScoreThreshold, setQuickScoreThreshold] = useState(DEFAULT_QUICK_SCORE_THRESHOLD);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [quickScores, setQuickScores] = useState<Record<string, QuickJobScore>>({});
  const [quickScoringJobIds, setQuickScoringJobIds] = useState<string[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [tasks, setTasks] = useState<BrowserTask[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeSearchRequest = useRef<string | null>(null);
  const maxJobsRef = useRef(maxJobs);
  maxJobsRef.current = maxJobs;
  const searchInputsEdited = useRef(false);
  const searchTimeout = useRef<number | null>(null);
  const importQueue = useRef<Promise<void>>(Promise.resolve());
  const quickScoreRequestedIds = useRef(new Set<string>());
  const captureStats = useRef({
    created: 0,
    updated: 0,
    detailed: 0,
    importedExternalIds: new Set<string>(),
    scheduledExternalIds: new Set<string>(),
  });
  const [collectionProgress, setCollectionProgress] = useState({ collected: 0, target: 0, persisted: 0 });
  const [backgroundSearchTask, setBackgroundSearchTask] = useState<BossBackgroundSearchTask | null>(null);

  const resetCollectionTimeout = useCallback((requestId: string) => {
    if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
    searchTimeout.current = window.setTimeout(() => {
      if (activeSearchRequest.current !== requestId) return;
      activeSearchRequest.current = null;
      setStage("idle");
      setError("扩展超过 90 秒没有返回新的采集进度。请检查 BOSS 标签页是否需要登录、验证或人工处理。");
    }, COLLECTION_INACTIVITY_TIMEOUT_MS);
  }, []);

  const scoreNewJobs = useCallback(async (
    jobIds: string[],
    scoreThreshold = quickScoreThreshold,
  ): Promise<QuickJobScore[] | null> => {
    const uniqueJobIds = [...new Set(jobIds.filter(Boolean))];
    const pendingJobIds = uniqueJobIds.filter((id) => !quickScoreRequestedIds.current.has(id));
    if (pendingJobIds.length === 0) return [];
    pendingJobIds.forEach((id) => quickScoreRequestedIds.current.add(id));
    setQuickScoringJobIds((current) => [...new Set([...current, ...pendingJobIds])]);
    try {
      const result = await quickScoreJobs({
        job_ids: pendingJobIds,
        ...(resumeId ? { resume_id: resumeId } : {}),
      });
      setQuickScores((current) => {
        const merged = { ...current };
        result.items.forEach((item) => { merged[item.job_id] = item; });
        return merged;
      });
      setSelectedJobIds((current) => {
        const selected = new Set(current);
        result.items.forEach((item) => {
          if (item.score >= scoreThreshold) selected.add(item.job_id);
          else selected.delete(item.job_id);
        });
        return [...selected];
      });
      return result.items;
    } catch (reason) {
      pendingJobIds.forEach((id) => quickScoreRequestedIds.current.delete(id));
      setError(reason instanceof Error ? reason.message : "岗位快速评分失败；新岗位已保持未勾选，请稍后重试。");
      return null;
    } finally {
      setQuickScoringJobIds((current) => current.filter((id) => !pendingJobIds.includes(id)));
    }
  }, [quickScoreThreshold, resumeId]);

  const applyBackgroundTask = useCallback((task: BossBackgroundSearchTask) => {
    const restoredThreshold = Math.min(100, Math.max(0, task.quick_score_threshold ?? DEFAULT_QUICK_SCORE_THRESHOLD));
    setBackgroundSearchTask(task);
    const restoredJobs: Job[] = task.persisted_jobs.map((job) => ({
      id: job.id,
      platform: "boss",
      external_job_id: job.external_job_id,
      company_id: null,
      title: job.title,
      description: "",
      location: job.location,
      salary_min: null,
      salary_max: null,
      job_type: null,
      education_requirement: null,
      experience_requirement: null,
      publish_time: null,
      source_url: null,
      raw_data: {
        company_name: job.company_name,
        salary_text: job.salary_text,
        description_source: job.description_source,
      },
      normalized_data: {},
      content_hash: null,
      created_at: task.started_at,
      updated_at: task.updated_at,
    }));
    setRequirements(task.requirements);
    setCity(task.city);
    setMaxJobs(task.target_count);
    setQuickScoreThreshold(restoredThreshold);
    setJobs(restoredJobs);
    setSelectedJobIds((current) => current.filter((id) => restoredJobs.some((job) => job.id === id)));
    void scoreNewJobs(restoredJobs.map((job) => job.id), restoredThreshold);
    setCollectionProgress({
      collected: task.collected_count,
      target: task.target_count,
      persisted: task.persisted_count,
    });
    captureStats.current = {
      created: task.created_count,
      updated: task.updated_count,
      detailed: task.detailed_count,
      importedExternalIds: new Set(task.persisted_jobs.map((job) => job.external_job_id).filter((id): id is string => Boolean(id))),
      scheduledExternalIds: new Set(task.persisted_jobs.map((job) => job.external_job_id).filter((id): id is string => Boolean(id))),
    };
    if (task.status === "RUNNING") {
      activeSearchRequest.current = task.request_id;
      resetCollectionTimeout(task.request_id);
      setStage("importing");
      setError(task.error ?? null);
      setNotice(`后台采集中：已读取 ${task.collected_count}/${task.target_count}，已持久化 ${task.persisted_count} 条。你可以离开此页面，扩展会继续运行。`);
      return;
    }
    activeSearchRequest.current = null;
    if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
    if (task.status === "COMPLETED") {
      setStage("ready");
      setError(null);
      setNotice(`后台采集完成：读取 ${task.collected_count} 条、持久化 ${task.persisted_count} 条，其中 ${task.detailed_count} 条包含完整 JD。`);
    } else if (task.status === "WAITING_FOR_USER") {
      setStage("idle");
      setError(task.error || `BOSS 页面状态为 ${task.page_state}，请完成页面验证后继续采集。`);
      setNotice(`采集已安全暂停：已读取 ${task.collected_count}/${task.target_count}，已持久化 ${task.persisted_count} 条；已完成的数据不会丢失。`);
    } else {
      setStage("idle");
      setError(task.error || `后台采集停止，页面状态为 ${task.page_state}。`);
    }
  }, [resetCollectionTimeout, scoreNewJobs]);

  const importCaptureBatch = useCallback(async (
    pageUrl: string,
    batch: BossVisibleJobCapture[],
    collectedCount: number,
    targetCount: number,
  ) => {
    if (!pageUrl || batch.length === 0) return;
    const imported = await importBossVisibleJobs({ page_url: pageUrl, jobs: batch });
    const stats = captureStats.current;
    stats.created += imported.created;
    stats.updated += imported.updated;
    stats.detailed += imported.items.filter((job) => job.raw_data.description_source === "detail_panel").length;
    batch.forEach((job) => stats.importedExternalIds.add(job.external_job_id));
    setJobs((current) => {
      const merged = new Map(current.map((job) => [job.id, job]));
      imported.items.forEach((job) => merged.set(job.id, job));
      return [...merged.values()];
    });
    const quickResults = await scoreNewJobs(imported.items.map((job) => job.id));
    const lowScoreCount = quickResults?.filter((item) => item.score < quickScoreThreshold).length ?? 0;
    setCollectionProgress({
      collected: collectedCount,
      target: targetCount,
      persisted: stats.importedExternalIds.size,
    });
    setNotice(
      `渐进采集中：已读取 ${collectedCount}/${targetCount}，已持久化 ${stats.importedExternalIds.size} 条；` +
      (lowScoreCount > 0
        ? `其中 ${lowScoreCount} 个岗位与当前简历符合度低于 ${quickScoreThreshold} 分，已置后且默认未勾选，请手动确认。`
        : "新岗位已完成快速评分并更新选择状态。"),
    );
  }, [quickScoreThreshold, scoreNewJobs]);

  const queueCaptureBatch = useCallback((
    pageUrl: string,
    batch: BossVisibleJobCapture[],
    collectedCount: number,
    targetCount: number,
  ): Promise<void> => {
    const stats = captureStats.current;
    const pending = batch.filter((job) => !stats.scheduledExternalIds.has(job.external_job_id));
    pending.forEach((job) => stats.scheduledExternalIds.add(job.external_job_id));
    if (pending.length === 0) return importQueue.current;
    const run = importQueue.current.then(() => importCaptureBatch(
      pageUrl,
      pending,
      collectedCount,
      targetCount,
    )).catch((reason) => {
      pending.forEach((job) => stats.scheduledExternalIds.delete(job.external_job_id));
      throw reason;
    });
    importQueue.current = run.catch(() => undefined);
    return run;
  }, [importCaptureBatch]);

  const processCapture = useCallback(async (result: CaptureResult) => {
    if (!result.success) {
      await importQueue.current;
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
      await queueCaptureBatch(
        result.page_url,
        result.jobs,
        result.jobs.length,
        result.jobs.length,
      );
      await importQueue.current;
      const stats = captureStats.current;
      setCollectionProgress({
        collected: result.jobs.length,
        target: result.jobs.length,
        persisted: stats.importedExternalIds.size,
      });
      setNotice(`采集并持久化完成：新增 ${stats.created} 条，更新完整 JD ${stats.updated} 条；本次 ${stats.detailed}/${stats.importedExternalIds.size} 条已获取完整 JD。`);
      setStage("ready");
    } catch (reason) {
      setStage("idle");
      setError(reason instanceof Error ? reason.message : "BOSS 职位导入失败。");
    }
  }, [queueCaptureBatch]);

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
        window.postMessage({
          source: "careerpilot-web",
          type: "BOSS_SEARCH_STATUS_REQUEST",
          request_id: window.crypto.randomUUID(),
        }, window.location.origin);
        return;
      }
      if (message.type === "BOSS_SEARCH_STATUS_RESULT") {
        if (message.task && !searchInputsEdited.current) applyBackgroundTask(message.task);
        return;
      }
      if (message.type === "BOSS_SEARCH_PROGRESS" && message.request_id === activeSearchRequest.current) {
        if (message.background_task) {
          applyBackgroundTask(message.background_task);
          return;
        }
        const collected = message.collected_count ?? 0;
        const target = message.target_count ?? maxJobsRef.current;
        resetCollectionTimeout(message.request_id);
        setStage("importing");
        setCollectionProgress((current) => ({ ...current, collected, target }));
        void queueCaptureBatch(
          message.page_url ?? "",
          message.jobs ?? [],
          collected,
          target,
        ).catch((reason) => {
          setError(reason instanceof Error ? reason.message : "增量持久化 BOSS 职位失败。");
        });
        return;
      }
      if (message.type !== "BOSS_SEARCH_RESULT" || message.request_id !== activeSearchRequest.current) return;
      activeSearchRequest.current = null;
      if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
      if (message.background_task) {
        applyBackgroundTask(message.background_task);
        return;
      }
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
  }, [applyBackgroundTask, processCapture, queueCaptureBatch, resetCollectionTimeout]);

  function startSearch() {
    if (!requirements.trim() || extensionStatus !== "connected") return;
    searchInputsEdited.current = true;
    const requestId = window.crypto.randomUUID();
    const requestedMaxJobs = Math.min(Math.max(maxJobs, 1), MAX_VISIBLE_BOSS_JOBS);
    const requestedScoreThreshold = Math.min(100, Math.max(0, quickScoreThreshold));
    activeSearchRequest.current = requestId;
    setStage("searching");
    setJobs([]);
    setQuickScores({});
    setQuickScoringJobIds([]);
    setSelectedJobIds([]);
    setTasks([]);
    setConfirmed(false);
    setError(null);
    setBackgroundSearchTask(null);
    setQuickScoreThreshold(requestedScoreThreshold);
    importQueue.current = Promise.resolve();
    quickScoreRequestedIds.current.clear();
    captureStats.current = {
      created: 0,
      updated: 0,
      detailed: 0,
      importedExternalIds: new Set<string>(),
      scheduledExternalIds: new Set<string>(),
    };
    setCollectionProgress({ collected: 0, target: requestedMaxJobs, persisted: 0 });
    setNotice("后台采集任务已启动。你可以切换到其他 CareerPilot 页面；扩展会持续采集并直接入库，返回此页即可恢复进度。如需登录或验证，请手动切换到 BOSS 标签页处理。");
    window.postMessage({
      source: "careerpilot-web",
      type: "BOSS_SEARCH_REQUEST",
      request_id: requestId,
      payload: {
        requirements: requirements.trim(),
        city: city.trim(),
        max_jobs: requestedMaxJobs,
        quick_score_threshold: requestedScoreThreshold,
      },
    }, window.location.origin);
    resetCollectionTimeout(requestId);
  }

  function clearRetrievedJobs() {
    if (busy) return;
    searchInputsEdited.current = true;
    activeSearchRequest.current = null;
    if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
    setStage("idle");
    setJobs([]);
    setQuickScores({});
    setQuickScoringJobIds([]);
    setSelectedJobIds([]);
    setTasks([]);
    setConfirmed(false);
    setCollectionProgress({ collected: 0, target: 0, persisted: 0 });
    captureStats.current = {
      created: 0,
      updated: 0,
      detailed: 0,
      importedExternalIds: new Set<string>(),
      scheduledExternalIds: new Set<string>(),
    };
    quickScoreRequestedIds.current.clear();
    setError(null);
    setBackgroundSearchTask(null);
    setNotice("已清空本次检索结果。已入库的岗位仍保留在岗位库中；现在可以修改条件后重新检索。");
  }

  function resumeSearch() {
    if (extensionStatus !== "connected" || backgroundSearchTask?.status !== "WAITING_FOR_USER") return;
    const requestId = backgroundSearchTask.request_id;
    activeSearchRequest.current = requestId;
    setStage("searching");
    setError(null);
    setNotice(`正在从 ${backgroundSearchTask.collected_count}/${backgroundSearchTask.target_count} 的检查点继续采集；已入库岗位会自动去重。`);
    window.postMessage({
      source: "careerpilot-web",
      type: "BOSS_SEARCH_RESUME_REQUEST",
      request_id: requestId,
    }, window.location.origin);
    resetCollectionTimeout(requestId);
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
  const canResumeCollection = backgroundSearchTask?.status === "WAITING_FOR_USER"
    && ["RISK_CONTROL", "CAPTCHA", "LOGIN_REQUIRED"].includes(backgroundSearchTask.page_state);
  const orderedJobs = [...jobs].sort((left, right) => {
    const leftScore = quickScores[left.id]?.score;
    const rightScore = quickScores[right.id]?.score;
    const leftPending = leftScore === undefined;
    const rightPending = rightScore === undefined;
    if (leftPending !== rightPending) return leftPending ? -1 : 1;
    if (leftScore === undefined || rightScore === undefined) return 0;
    const leftLow = leftScore < quickScoreThreshold;
    const rightLow = rightScore < quickScoreThreshold;
    if (leftLow !== rightLow) return leftLow ? 1 : -1;
    return rightScore - leftScore;
  });

  return (
    <section className="panel overflow-hidden border-indigo-200">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">BOSS Extension Workflow</p>
          <h2 className="mt-2 text-xl font-semibold">按要求采集并对接投递</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">扩展会在后台新建 BOSS 标签页，以较快但受控的节奏逐卡平滑滚动并采集。任务不依赖当前页面存活，你可以继续使用其他功能；每取得一个完整 JD 就由扩展后台立即持久化。登录、验证码、风控或平台限制仍会暂停等待人工处理。</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${extensionStatus === "connected" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
          {extensionStatus === "connected" ? `插件已连接 ${extensionVersion}` : extensionStatus === "checking" ? "正在检测插件" : "未检测到插件"}
        </span>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(180px,1fr)_140px_160px]">
        <label className="text-sm font-medium text-slate-700">岗位要求
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" maxLength={200} onChange={(event) => { searchInputsEdited.current = true; setRequirements(event.target.value); }} placeholder="例如：AI Agent、RAG、Python 实习" value={requirements} />
        </label>
        <label className="text-sm font-medium text-slate-700">城市
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" maxLength={30} onChange={(event) => { searchInputsEdited.current = true; setCity(event.target.value); }} placeholder="北京" value={city} />
        </label>
        <label className="text-sm font-medium text-slate-700">最多采集（1–200）
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" max={MAX_VISIBLE_BOSS_JOBS} min={1} onChange={(event) => { searchInputsEdited.current = true; setMaxJobs(Number(event.target.value) || 1); }} type="number" value={maxJobs} />
        </label>
        <label className="text-sm font-medium text-slate-700">快速评分阈值
          <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500 disabled:cursor-not-allowed disabled:opacity-60" disabled={busy} max={100} min={0} onChange={(event) => {
            const next = Math.min(100, Math.max(0, Number(event.target.value) || 0));
            setQuickScoreThreshold(next);
            setSelectedJobIds((current) => current.filter((id) => quickScores[id]?.score === undefined || quickScores[id].score >= next));
          }} type="number" value={quickScoreThreshold} />
        </label>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        {canResumeCollection && <button className="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || extensionStatus !== "connected"} onClick={resumeSearch} type="button">我已完成验证，继续采集</button>}
        <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || extensionStatus !== "connected" || !requirements.trim()} onClick={startSearch} type="button">
          {stage === "searching" || stage === "importing" ? "插件采集中…" : canResumeCollection ? "放弃续采并重新检索" : jobs.length > 0 ? "重新检索 BOSS" : "调动插件搜索 BOSS"}
        </button>
        {jobs.length > 0 && !busy && <button className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" onClick={clearRetrievedJobs} type="button">清空本次结果</button>}
        <a className="text-sm font-medium text-indigo-700" href="https://www.zhipin.com/web/geek/jobs" rel="noreferrer" target="_blank">手动打开 BOSS →</a>
        {canResumeCollection && backgroundSearchTask.page_url && <a className="text-sm font-medium text-amber-700" href={backgroundSearchTask.page_url} rel="noreferrer" target="_blank">打开待处理的 BOSS 页面 →</a>}
      </div>

      {extensionStatus === "missing" && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">请在浏览器扩展管理页加载或重新加载 <code>apps/extension/.output/chrome-mv3</code>，然后刷新此页面。插件连接只在本机浏览器内建立。</p>}
      {notice && <p className="mt-4 rounded-xl bg-indigo-50 p-4 text-sm leading-6 text-indigo-700">{notice}</p>}
      {error && <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm leading-6 text-rose-800">{error}</p>}
      {(stage === "searching" || stage === "importing") && collectionProgress.target > 0 && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex justify-between text-xs text-slate-500"><span>渐进采集与持久化</span><span>{collectionProgress.collected}/{collectionProgress.target} · 已入库 {collectionProgress.persisted}</span></div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${Math.min(100, collectionProgress.collected / collectionProgress.target * 100)}%` }} /></div>
      </div>}

      {jobs.length > 0 && <div className="mt-7 space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Imported Jobs</p><h3 className="mt-2 font-semibold">选择需要投递的职位</h3></div><span className="text-sm text-slate-500">已选 {selectedJobIds.length}/{jobs.length}</span></div>
        <div className="divide-y divide-slate-100 rounded-2xl border border-slate-200">
          {orderedJobs.map((job) => {
            const checked = selectedJobIds.includes(job.id);
            const company = typeof job.raw_data.company_name === "string" ? job.raw_data.company_name : "公司待补充";
            const salary = typeof job.raw_data.salary_text === "string" ? job.raw_data.salary_text : "薪资面议";
            const hasFullJd = job.raw_data.description_source === "detail_panel";
            const quickScore = quickScores[job.id];
            const isQuickScoring = quickScoringJobIds.includes(job.id);
            const isLowScore = quickScore !== undefined && quickScore.score < quickScoreThreshold;
            return <label className={`flex cursor-pointer items-start gap-4 p-4 ${isLowScore ? "bg-amber-50/70" : ""}`} key={job.id}>
              <input checked={checked} className="mt-1 h-4 w-4 accent-indigo-600" onChange={() => setSelectedJobIds((current) => checked ? current.filter((id) => id !== job.id) : [...current, job.id])} type="checkbox" />
              <span className="min-w-0 flex-1"><span className="font-medium">{job.title}</span><span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{hasFullJd ? "完整 JD" : "卡片摘要"}</span>{isQuickScoring && <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">快速评分中…</span>}{quickScore && <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${isLowScore ? "bg-amber-100 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>快速评分 {quickScore.score.toFixed(0)}</span>}<span className="mt-1 block text-sm text-slate-500">{company} · {job.location ?? "地点待补充"} · {salary}</span>{isLowScore && <span className="mt-2 block text-sm font-medium text-amber-800">与当前简历符合度不高，已默认不勾选并置后；如仍要投递，请手动勾选。</span>}</span>
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
