"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  createCuratedCampaign,
  getResumes,
  importBossVisibleJobs,
  quickScoreJobs,
  type BossVisibleJobCapture,
  type Job,
  type QuickJobScore,
  type Resume,
} from "../lib/api";

type ExtensionStatus = "checking" | "connected" | "missing";
type WorkflowStage = "idle" | "searching" | "importing" | "preparing" | "ready";

type BossExtensionMessage = {
  source: "careerpilot-extension";
  type: "BOSS_EXTENSION_PONG" | "BOSS_SEARCH_PROGRESS" | "BOSS_SEARCH_RESULT" | "BOSS_SEARCH_CANCEL_RESULT" | "BOSS_SEARCH_STATUS_RESULT" | "BOSS_TASK_LAUNCH_RESULT" | "BOSS_TASK_BATCH_LAUNCH_RESULT";
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
  status: "RUNNING" | "WAITING_FOR_USER" | "COMPLETED" | "FAILED" | "CANCELLED";
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

type BossPluginWorkflowProps = {
  onTasksCreated?: () => Promise<unknown> | void;
  onJobsPersisted?: (jobIds: string[]) => Promise<unknown> | void;
  onCollectionCompleted?: (jobIds: string[], collectionKey?: string) => Promise<unknown> | void;
  initialRequirements?: string;
  initialCity?: string;
  initialMaxJobs?: number;
  initialQuickScoreThreshold?: number;
  initialResumeId?: string;
  autoStart?: boolean;
  autoStartKey?: string;
  compact?: boolean;
};

export function BossPluginWorkflow({
  onTasksCreated,
  onJobsPersisted,
  onCollectionCompleted,
  initialRequirements = "AI Agent RAG 实习",
  initialCity = "北京",
  initialMaxJobs = 10,
  initialQuickScoreThreshold = DEFAULT_QUICK_SCORE_THRESHOLD,
  initialResumeId = "",
  autoStart = false,
  autoStartKey = "",
  compact = false,
}: BossPluginWorkflowProps) {
  const [extensionStatus, setExtensionStatus] = useState<ExtensionStatus>("checking");
  const [extensionVersion, setExtensionVersion] = useState("");
  const [stage, setStage] = useState<WorkflowStage>("idle");
  const [requirements, setRequirements] = useState(initialRequirements);
  const [city, setCity] = useState(initialCity);
  const [maxJobs, setMaxJobs] = useState(Math.min(200, Math.max(1, initialMaxJobs)));
  const [quickScoreThreshold, setQuickScoreThreshold] = useState(Math.min(100, Math.max(0, initialQuickScoreThreshold)));
  const [jobs, setJobs] = useState<Job[]>([]);
  const [quickScores, setQuickScores] = useState<Record<string, QuickJobScore>>({});
  const [quickScoringJobIds, setQuickScoringJobIds] = useState<string[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState(initialResumeId);
  const [createdPlan, setCreatedPlan] = useState<{ id: string; signature: string } | null>(null);
  const selectionSignature = JSON.stringify([resumeId, [...selectedJobIds].sort(), requirements.trim(), city.trim()]);
  const existingPlan = createdPlan?.signature === selectionSignature ? createdPlan : null;
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeSearchRequest = useRef<string | null>(null);
  const maxJobsRef = useRef(maxJobs);
  maxJobsRef.current = maxJobs;
  const searchInputsEdited = useRef(compact);
  const searchTimeout = useRef<number | null>(null);
  const stopTimeout = useRef<number | null>(null);
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
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const [stoppingCollection, setStoppingCollection] = useState(false);
  const autoStarted = useRef(false);
  const persistedJobIds = useRef(new Set<string>());
  const completionNotified = useRef(new Set<string>());

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
          if (item.score_status === "INSUFFICIENT_DATA" || item.score >= scoreThreshold) selected.add(item.job_id);
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
    task.persisted_jobs.forEach((job) => persistedJobIds.current.add(job.id));
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
      last_collected_at: task.updated_at,
      created_at: task.started_at,
      updated_at: task.updated_at,
    }));
    setRequirements(task.requirements);
    setCity(task.city);
    setMaxJobs(task.target_count);
    setQuickScoreThreshold(restoredThreshold);
    setJobs(restoredJobs);
    if (restoredJobs.length > 0) {
      void Promise.resolve(onJobsPersisted?.(restoredJobs.map((job) => job.id))).catch(
        () => undefined,
      );
    }
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
      setNotice(`正在可见页面采集：已读取 ${task.collected_count}/${task.target_count}，已持久化 ${task.persisted_count} 条。请保持 BOSS 标签页可见。`);
      return;
    }
    activeSearchRequest.current = null;
    if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
    if (task.status === "COMPLETED") {
      setStage("ready");
      setError(null);
      setNotice(`采集完成：读取 ${task.collected_count} 条、持久化 ${task.persisted_count} 条，其中 ${task.detailed_count} 条包含完整 JD。`);
    } else if (task.status === "WAITING_FOR_USER") {
      setStage("idle");
      setError(task.error || `BOSS 页面状态为 ${task.page_state}，请完成页面验证后继续采集。`);
      setNotice(`采集已安全暂停：已读取 ${task.collected_count}/${task.target_count}，已持久化 ${task.persisted_count} 条；已完成的数据不会丢失。`);
    } else if (task.status === "CANCELLED") {
      setStage(task.persisted_jobs.length > 0 ? "ready" : "idle");
      setError(null);
      setNotice(`职位采集已停止：已读取 ${task.collected_count}/${task.target_count}，已持久化 ${task.persisted_count} 条。已入库岗位和快速评分结果均已保留，你可以直接筛选或重新检索。`);
    } else {
      setStage("idle");
      setError(task.error || `采集停止，页面状态为 ${task.page_state}。`);
    }
  }, [onJobsPersisted, resetCollectionTimeout, scoreNewJobs]);

  useEffect(() => {
    const task = backgroundSearchTask;
    if (
      !onCollectionCompleted
      || !task
      || task.status !== "COMPLETED"
      || completionNotified.current.has(task.request_id)
    ) return;
    const jobIds = [...new Set([
      ...persistedJobIds.current,
      ...task.persisted_jobs.map((job) => job.id),
    ])].filter(Boolean);
    if (jobIds.length === 0) return;
    completionNotified.current.add(task.request_id);
    Promise.resolve(onCollectionCompleted(jobIds, task.request_id)).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "采集完成，自动续答启动失败，请重新发送问题。");
    });
  }, [backgroundSearchTask, onCollectionCompleted]);

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
    imported.items.forEach((job) => persistedJobIds.current.add(job.id));
    batch.forEach((job) => stats.importedExternalIds.add(job.external_job_id));
    setJobs((current) => {
      const merged = new Map(current.map((job) => [job.id, job]));
      imported.items.forEach((job) => merged.set(job.id, job));
      return [...merged.values()];
    });
    await onJobsPersisted?.(imported.items.map((job) => job.id));
    const quickResults = await scoreNewJobs(imported.items.map((job) => job.id));
    const lowScoreCount = quickResults?.filter((item) => item.score_status !== "INSUFFICIENT_DATA" && item.score < quickScoreThreshold).length ?? 0;
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
  }, [onJobsPersisted, quickScoreThreshold, scoreNewJobs]);

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
      const persistedIds = [...persistedJobIds.current];
      if (persistedIds.length > 0) {
        await onCollectionCompleted?.(persistedIds);
      }
    } catch (reason) {
      setStage("idle");
      setError(reason instanceof Error ? reason.message : "BOSS 职位导入失败。");
    }
  }, [onCollectionCompleted, queueCaptureBatch]);

  useEffect(() => {
    getResumes().then((response) => {
      setResumes(response.items);
      setResumeId((current) => response.items.some((resume) => resume.id === current)
        ? current
        : response.items.find((resume) => resume.is_default)?.id ?? response.items[0]?.id ?? "");
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
      if (message.type === "BOSS_SEARCH_CANCEL_RESULT") {
        if (stopTimeout.current) window.clearTimeout(stopTimeout.current);
        setStoppingCollection(false);
        setStopConfirmOpen(false);
        if (message.success && message.task) {
          applyBackgroundTask(message.task);
        } else {
          setError(message.error || "停止职位采集失败，请重试。");
        }
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
      if (stopTimeout.current) window.clearTimeout(stopTimeout.current);
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
    persistedJobIds.current.clear();
    completionNotified.current.clear();
    setQuickScores({});
    setQuickScoringJobIds([]);
    setSelectedJobIds([]);
    setCreatedPlan(null);
    setError(null);
    const startedAt = new Date().toISOString();
    setBackgroundSearchTask({
      request_id: requestId,
      status: "RUNNING",
      requirements: requirements.trim(),
      city: city.trim(),
      target_count: requestedMaxJobs,
      quick_score_threshold: requestedScoreThreshold,
      collected_count: 0,
      persisted_count: 0,
      created_count: 0,
      updated_count: 0,
      detailed_count: 0,
      page_url: "",
      page_state: "UNKNOWN_STATE",
      persisted_jobs: [],
      started_at: startedAt,
      updated_at: startedAt,
    });
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
    setNotice("已打开可见的 BOSS 采集标签页。采集期间请保持该标签页可见；如果切换到其他页面，采集会自动暂停，已入库岗位会保留。");
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

  useEffect(() => {
    if (!autoStart || autoStarted.current || extensionStatus !== "connected" || !requirements.trim() || !resumeId) return;
    const storageKey = `careerpilot:advisor-collection:${autoStartKey || requirements}`;
    try {
      if (window.localStorage.getItem(storageKey)) {
        autoStarted.current = true;
        return;
      }
      window.localStorage.setItem(storageKey, "started");
    } catch { /* A disabled session store should not block an explicit user request. */ }
    autoStarted.current = true;
    startSearch();
    // The action is immutable for one mounted chat message.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, autoStartKey, extensionStatus, resumeId]);

  function clearRetrievedJobs() {
    if (busy) return;
    searchInputsEdited.current = true;
    activeSearchRequest.current = null;
    if (searchTimeout.current) window.clearTimeout(searchTimeout.current);
    setStage("idle");
    setJobs([]);
    persistedJobIds.current.clear();
    completionNotified.current.clear();
    setQuickScores({});
    setQuickScoringJobIds([]);
    setSelectedJobIds([]);
    setCreatedPlan(null);
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

  function stopSearch() {
    if (extensionStatus !== "connected" || !backgroundSearchTask || !["RUNNING", "WAITING_FOR_USER"].includes(backgroundSearchTask.status)) return;
    setStoppingCollection(true);
    setError(null);
    setNotice("正在停止职位采集；扩展会在当前岗位处理完成后终止滚动和入库。已完成的数据会保留。");
    window.postMessage({
      source: "careerpilot-web",
      type: "BOSS_SEARCH_CANCEL_REQUEST",
      request_id: backgroundSearchTask.request_id,
    }, window.location.origin);
    if (stopTimeout.current) window.clearTimeout(stopTimeout.current);
    stopTimeout.current = window.setTimeout(() => {
      setStoppingCollection(false);
      setStopConfirmOpen(false);
      setError("扩展没有响应停止指令。请在扩展管理页重新加载最新的 CareerPilot Browser Agent，然后重试；当前采集状态未被页面擅自修改。");
    }, 8_000);
  }

  async function createSelectedPlan() {
    if (!resumeId || selectedJobIds.length === 0 || existingPlan || stage === "preparing") return;
    setStage("preparing");
    setError(null);
    setNotice("正在将勾选职位保存到投递计划…");
    try {
      const campaign = await createCuratedCampaign({
        name: `BOSS · ${requirements.trim().slice(0, 60)}`,
        resume_id: resumeId,
        job_ids: selectedJobIds,
        query: [requirements.trim(), city.trim()].filter(Boolean).join(" · "),
      });
      setCreatedPlan({ id: campaign.id, signature: selectionSignature });
      setNotice(campaign.reused_existing ? "相同选择已有投递计划，已为你找到原计划，未重复创建或投递。" : `已将 ${selectedJobIds.length} 个岗位保存到计划。请进入计划确认岗位，再启动投递。`);
      setStage("ready");
      try { await onTasksCreated?.(); } catch { /* The persisted plan remains available. */ }
    } catch (reason) {
      setStage("ready");
      setError(reason instanceof Error ? reason.message : "投递计划保存失败，请重试；勾选结果已保留。");
    }
  }

  const busy = stage === "searching" || stage === "importing" || stage === "preparing";
  const canResumeCollection = backgroundSearchTask?.status === "WAITING_FOR_USER"
    && ["RISK_CONTROL", "CAPTCHA", "LOGIN_REQUIRED", "TAB_HIDDEN"].includes(backgroundSearchTask.page_state);
  const collectionTabHidden = backgroundSearchTask?.page_state === "TAB_HIDDEN";
  const canStopCollection = backgroundSearchTask !== null
    && ["RUNNING", "WAITING_FOR_USER"].includes(backgroundSearchTask.status);
  const orderedJobs = [...jobs].sort((left, right) => {
    const leftScore = quickScores[left.id]?.score;
    const rightScore = quickScores[right.id]?.score;
    const leftPending = leftScore === undefined;
    const rightPending = rightScore === undefined;
    if (leftPending !== rightPending) return leftPending ? -1 : 1;
    if (leftScore === undefined || rightScore === undefined) return 0;
    const leftLow = quickScores[left.id]?.score_status !== "INSUFFICIENT_DATA" && leftScore < quickScoreThreshold;
    const rightLow = quickScores[right.id]?.score_status !== "INSUFFICIENT_DATA" && rightScore < quickScoreThreshold;
    if (leftLow !== rightLow) return leftLow ? 1 : -1;
    return rightScore - leftScore;
  });
  const displayedJobs = compact
    ? orderedJobs.filter((job) => {
        const score = quickScores[job.id];
        return score !== undefined && score.score_status !== "INSUFFICIENT_DATA" && score.score >= quickScoreThreshold;
      })
    : orderedJobs;

  return (
    <section className="panel overflow-hidden border-indigo-200">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">{compact ? "Agent Tool · 联网岗位检索" : "BOSS Extension Workflow"}</p>
          <h2 className="mt-2 text-xl font-semibold">{compact ? `正在搜索：${requirements}` : "从 BOSS 采集岗位"}</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">扩展会打开 BOSS 搜索标签页，逐卡读取并实时保存完整 JD。职位卡片加载完成后可切回本系统；浏览器节电策略可能让后台加载变慢，若任务停滞可重新打开 BOSS 标签继续。登录、验证码、风控或平台限制仍会暂停等待人工处理。</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${extensionStatus === "connected" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
          {extensionStatus === "connected" ? `插件已连接 ${extensionVersion}` : extensionStatus === "checking" ? "正在检测插件" : "未检测到插件"}
        </span>
      </div>

      {!compact && <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(180px,1fr)_140px_160px]">
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
            setSelectedJobIds((current) => current.filter((id) => quickScores[id]?.score === undefined || quickScores[id].score_status === "INSUFFICIENT_DATA" || quickScores[id].score >= next));
          }} type="number" value={quickScoreThreshold} />
        </label>
      </div>}
      <div className="mt-5 flex flex-wrap items-center gap-3">
        {canResumeCollection && <button className="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || extensionStatus !== "connected"} onClick={resumeSearch} type="button">{collectionTabHidden ? "保持 BOSS 可见，继续采集" : "我已完成处理，继续采集"}</button>}
        {canStopCollection && <button className="rounded-xl border border-rose-300 bg-rose-50 px-5 py-3 text-sm font-medium text-rose-700 transition hover:border-rose-400 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50" disabled={stoppingCollection || extensionStatus !== "connected"} onClick={() => setStopConfirmOpen(true)} type="button">{stoppingCollection ? "正在停止…" : "停止采集"}</button>}
        <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || extensionStatus !== "connected" || !requirements.trim()} onClick={startSearch} type="button">
          {stage === "searching" || stage === "importing" ? "插件采集中…" : canResumeCollection ? "放弃续采并重新检索" : jobs.length > 0 ? "重新检索 BOSS" : "调动插件搜索 BOSS"}
        </button>
        {jobs.length > 0 && !busy && <button className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" onClick={clearRetrievedJobs} type="button">清空本次结果</button>}
        {!compact && <a className="text-sm font-medium text-indigo-700" href="https://www.zhipin.com/web/geek/jobs" rel="noreferrer" target="_blank">手动打开 BOSS →</a>}
        {canResumeCollection && backgroundSearchTask.page_url && <a className="text-sm font-medium text-amber-700" href={backgroundSearchTask.page_url} rel="noreferrer" target="_blank">打开并保持 BOSS 页面可见 →</a>}
      </div>

      {extensionStatus === "missing" && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">请在浏览器扩展管理页加载或重新加载 <code>apps/extension/.output/chrome-mv3</code>，然后刷新此页面。插件连接只在本机浏览器内建立。</p>}
      {compact && resumes.length === 0 && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200">联网采集需要一份简历用于快速评分。请先到简历管理上传简历，再返回本消息启动采集。</p>}
      {notice && <p className="mt-4 rounded-xl bg-indigo-50 p-4 text-sm leading-6 text-indigo-700">{notice}</p>}
      {error && <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm leading-6 text-rose-800">{error}</p>}
      {(stage === "searching" || stage === "importing") && collectionProgress.target > 0 && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex justify-between text-xs text-slate-500"><span>渐进采集与持久化</span><span>{collectionProgress.collected}/{collectionProgress.target} · 已入库 {collectionProgress.persisted}</span></div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${Math.min(100, collectionProgress.collected / collectionProgress.target * 100)}%` }} /></div>
      </div>}

      {jobs.length > 0 && <div className="mt-7 space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Imported Jobs</p><h3 className="mt-2 font-semibold">{compact ? "达到阈值的高匹配岗位" : "选择需要投递的职位"}</h3></div><span className="text-sm text-slate-500">{compact ? `高分 ${displayedJobs.length} · 已采集 ${jobs.length}` : `已选 ${selectedJobIds.length}/${jobs.length}`}</span></div>
        {compact && displayedJobs.length === 0 && <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-900 dark:text-slate-400">岗位正在评分，或暂时没有达到 {quickScoreThreshold} 分的岗位。低分岗位不会在聊天推荐卡片中展示。</p>}
        <div className="divide-y divide-slate-100 rounded-2xl border border-slate-200">
          {displayedJobs.map((job) => {
            const checked = selectedJobIds.includes(job.id);
            const company = typeof job.raw_data.company_name === "string" ? job.raw_data.company_name : "公司待补充";
            const salary = typeof job.raw_data.salary_text === "string" ? job.raw_data.salary_text : "薪资面议";
            const hasFullJd = job.raw_data.description_source === "detail_panel";
            const quickScore = quickScores[job.id];
            const isQuickScoring = quickScoringJobIds.includes(job.id);
            const isInsufficient = quickScore?.score_status === "INSUFFICIENT_DATA";
            const isLowScore = quickScore !== undefined && !isInsufficient && quickScore.score < quickScoreThreshold;
            return <label className={`flex cursor-pointer items-start gap-4 p-4 ${isLowScore ? "cp-low-match-surface" : ""}`} key={job.id}>
              <input checked={checked} className="mt-1 h-4 w-4 accent-indigo-600" onChange={() => setSelectedJobIds((current) => checked ? current.filter((id) => id !== job.id) : [...current, job.id])} type="checkbox" />
              <span className="min-w-0 flex-1"><span className="font-medium">{job.title}</span><span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">{hasFullJd ? "完整 JD" : "卡片摘要"}</span>{isQuickScoring && <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200">快速评分中…</span>}{quickScore && <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${isInsufficient ? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" : isLowScore ? "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200" : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-200"}`} title="匹配分表示岗位符合程度；置信度表示系统对该结果的可靠程度">{isInsufficient ? "JD 信息不足，暂不判低分" : `快速评分 ${quickScore.score.toFixed(0)}`} · 置信度 {(quickScore.score_confidence * 100).toFixed(0)}%</span>}<span className="mt-1 block text-sm text-slate-500 dark:text-slate-400">{company} · {job.location ?? "地点待补充"} · {salary}</span>{quickScore && !quickScore.hard_constraint_passed && <span className="mt-2 block text-sm font-medium text-rose-700 dark:text-rose-300">存在硬性条件不满足：{quickScore.rule_reasons.join("；")}</span>}{isInsufficient && <span className="mt-2 block text-sm text-slate-600 dark:text-slate-300">职位描述不足，系统暂时无法可靠判断匹配程度，请查看详情后人工确认。</span>}{isLowScore && <span className="mt-2 block text-sm font-medium text-amber-800 dark:text-amber-200">与当前简历符合度不高，已默认不勾选并置后；如仍要投递，请手动勾选。</span>}</span>
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
          <p className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-600">保存计划不会自动投递。你可以在计划详情中剔除岗位、确认入队，然后启动投递。</p>
        </div>
        {resumes.length === 0 && <p className="text-sm text-amber-700">还没有可用简历，请先前往 <Link className="font-medium underline" href="/resume">简历管理</Link> 上传并解析。</p>}
        <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || selectedJobIds.length === 0 || !resumeId || !!existingPlan} onClick={() => void createSelectedPlan()} type="button">
          {stage === "preparing" ? "正在保存计划…" : existingPlan ? "这些岗位已加入计划" : `将 ${selectedJobIds.length} 个岗位加入投递计划`}
        </button>
      </div>}

      {existingPlan && <Link className="mt-5 inline-block rounded-xl border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700" href={`/campaigns/${existingPlan.id}`}>查看并确认投递计划 →</Link>}

      {stopConfirmOpen && <div aria-labelledby="stop-boss-collection-title" aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4" role="dialog">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
          <p className="eyebrow">停止职位采集</p>
          <h3 className="mt-2 text-lg font-semibold" id="stop-boss-collection-title">确定停止当前采集任务？</h3>
          <p className="mt-3 text-sm leading-6 text-slate-500">扩展将停止读取新岗位和滚动 BOSS 列表。已经持久化的 {backgroundSearchTask?.persisted_count ?? collectionProgress.persisted} 个岗位会保留，之后仍可筛选、评分和加入投递计划。</p>
          <div className="mt-6 flex justify-end gap-3">
            <button className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300" disabled={stoppingCollection} onClick={() => setStopConfirmOpen(false)} type="button">继续采集</button>
            <button className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-rose-700 disabled:opacity-50" disabled={stoppingCollection} onClick={stopSearch} type="button">{stoppingCollection ? "正在停止…" : "确认停止"}</button>
          </div>
        </div>
      </div>}
    </section>
  );
}

function isExtensionMessage(value: unknown): value is BossExtensionMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as Partial<BossExtensionMessage>;
  return message.source === "careerpilot-extension" && typeof message.type === "string" && typeof message.request_id === "string";
}
