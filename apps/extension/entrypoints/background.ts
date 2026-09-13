import { waitForTabComplete } from "../lib/browser-navigation";
import { deliveryPlatform } from "../lib/delivery-url";
import { handleZhaopinCollection } from "../lib/zhaopin-collection";
import { buildBossSearchUrl, isBossPageUrl, matchesBossJobSearch, MAX_BOSS_BATCH_JOBS } from "../lib/platforms/boss";
import type {
  ActionMessage,
  ActionResultMessage,
  BossTaskBatchLaunchRequest,
  BossBackgroundSearchTask,
  BossBridgeResponse,
  BossCaptureProgress,
  BossCaptureResponse,
  BossPersistedJobSummary,
  BossSearchCancelRequest,
  BossSearchRequest,
  BossSearchResumeRequest,
  BossTaskLaunchRequest,
  BrowserTaskBatchLifecycleMessage,
  BrowserTaskLifecycleMessage,
  RecruitmentBridgeRequest,
  RecruitmentBridgeResponse,
  ZhaopinCaptureRequest,
  ZhaopinCaptureResponse,
} from "../lib/protocol";

const API_WS_BASE = "ws://localhost:8010/api/browser-tasks/ws/";
const API_BASE_URL = "http://localhost:8010";
const BOSS_SEARCH_STORAGE_KEY = "careerpilot_boss_background_search";
const RESUMABLE_BOSS_SEARCH_STATES = new Set(["CAPTCHA", "LOGIN_REQUIRED", "RISK_CONTROL", "TAB_HIDDEN"]);
const sockets = new Map<string, WebSocket>();
const activeTabs = new Map<string, number>();
const activeSearchOrigins = new Map<string, number>();
const cancelledBossSearchRequests = new Set<string>();
const batchQueue: Array<{ task_id: string; url: string }> = [];
let batchTabId: number | null = null;
let activeBatchTaskId: string | null = null;

export default defineBackground(() => {
  browser.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (changeInfo.status !== "complete" || !tab.url) return;
    const taskId = new URL(tab.url).searchParams.get("task");
    if (taskId) {
      activeTabs.set(taskId, tabId);
      connectTask(taskId, tabId);
    }
  });

  browser.runtime.onMessage.addListener(async (
    message: ActionResultMessage | RecruitmentBridgeRequest | BossCaptureProgress,
    sender,
  ): Promise<RecruitmentBridgeResponse | undefined> => {
    if (message.type === "BOSS_CAPTURE_PROGRESS") {
      await forwardBossSearchProgress(message);
      return;
    }
    if (message.type === "ZHAOPIN_CAPTURE_REQUEST") return captureZhaopinVisible(message);
    if (message.type === "ZHAOPIN_SEARCH_REQUEST" || message.type === "ZHAOPIN_SEARCH_STATUS_REQUEST" || message.type === "ZHAOPIN_SEARCH_CANCEL_REQUEST" || message.type === "ZHAOPIN_SEARCH_RESUME_REQUEST" || message.type === "ZHAOPIN_SEARCH_OPEN_REQUEST") return handleZhaopinCollection(message);
    if (message.type === "BOSS_SEARCH_REQUEST") return runBossSearch(message, sender.tab?.id);
    if (message.type === "BOSS_SEARCH_RESUME_REQUEST") return resumeBossSearch(message, sender.tab?.id);
    if (message.type === "BOSS_SEARCH_CANCEL_REQUEST") return cancelBossSearch(message);
    if (message.type === "BOSS_SEARCH_STATUS_REQUEST") {
      return {
        source: "careerpilot-extension",
        type: "BOSS_SEARCH_STATUS_RESULT",
        request_id: message.request_id,
        task: await getStoredBossSearch(),
      };
    }
    if (message.type === "BOSS_TASK_LAUNCH_REQUEST") return launchBossTask(message);
    if (message.type === "BOSS_TASK_BATCH_LAUNCH_REQUEST" || message.type === "RECRUITMENT_TASK_BATCH_LAUNCH_REQUEST") return launchBossTaskBatch(message);
    if (message.type !== "ACTION_RESULT") return;
    const tabId = sender.tab?.id;
    const taskId = [...activeTabs.entries()].find(([, activeTabId]) => activeTabId === tabId)?.[0];
    if (!taskId) return;
    sockets.get(taskId)?.send(JSON.stringify(message));
  });
});

async function captureZhaopinVisible(
  message: ZhaopinCaptureRequest,
): Promise<ZhaopinCaptureResponse> {
  // Manual capture must always target the tab the user can currently see.
  // Never scrape an arbitrary inactive recruitment tab left over from an
  // earlier task.
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  const tab = tabs.find((item) => item.id !== undefined);
  if (!tab?.id) {
    return {
      source: "careerpilot-extension",
      type: "ZHAOPIN_CAPTURE_RESULT",
      request_id: message.request_id,
      success: false,
      page_url: "",
      jobs: [],
      page_state: "UNKNOWN_STATE",
      error: "没有找到已打开的智联招聘标签页，请先打开智联招聘搜索结果页。",
    };
  }
  try {
    const response = await browser.tabs.sendMessage(tab.id, {
      type: "CAPTURE_ZHAOPIN_VISIBLE",
      request_id: message.request_id,
      max_jobs: message.max_jobs,
    });
    return {
      ...(response as ZhaopinCaptureResponse),
      source: "careerpilot-extension",
      request_id: message.request_id,
    };
  } catch (error) {
    return {
      source: "careerpilot-extension",
      type: "ZHAOPIN_CAPTURE_RESULT",
      request_id: message.request_id,
      success: false,
      page_url: tab.url || "",
      jobs: [],
      page_state: "UNKNOWN_STATE",
      error: error instanceof Error
        ? error.message
        : "无法连接智联招聘页面内容脚本，请刷新页面后重试。",
    };
  }
}

async function runBossSearch(
  message: BossSearchRequest,
  originTabId?: number,
): Promise<BossBridgeResponse> {
  if (originTabId !== undefined) activeSearchOrigins.set(message.request_id, originTabId);
  let task: BossBackgroundSearchTask | null = null;
  try {
    const requirements = message.payload.requirements.trim();
    const maxJobs = Math.min(Math.max(message.payload.max_jobs, 1), MAX_BOSS_BATCH_JOBS);
    const quickScoreThreshold = Math.min(Math.max(message.payload.quick_score_threshold, 0), 100);
    if (!requirements) throw new Error("请填写岗位要求");
    const existing = await getStoredBossSearch();
    if (existing?.status === "RUNNING" && existing.request_id !== message.request_id) {
      throw new Error("已有 BOSS 可见采集任务正在运行，请等待其完成后再启动新任务");
    }
    cancelledBossSearchRequests.delete(message.request_id);
    const now = new Date().toISOString();
    task = {
      request_id: message.request_id,
      status: "RUNNING",
      requirements,
      city: message.payload.city.trim(),
      target_count: maxJobs,
      quick_score_threshold: quickScoreThreshold,
      collected_count: 0,
      persisted_count: 0,
      created_count: 0,
      updated_count: 0,
      detailed_count: 0,
      page_url: "",
      page_state: "UNKNOWN_STATE",
      persisted_jobs: [],
      started_at: now,
      updated_at: now,
    };
    await storeBossSearch(task);
    const tab = await browser.tabs.create({
      active: true,
      url: buildBossSearchUrl(requirements, message.payload.city),
    });
    if (!tab.id) throw new Error("无法创建 BOSS 搜索标签页");
    task = { ...task, tab_id: tab.id, updated_at: new Date().toISOString() };
    await storeBossSearch(task);
    await waitForTabComplete(tab.id);
    const capture = await captureVisibleJobs(tab.id, maxJobs, message.request_id);
    const latestTask = await getStoredBossSearch();
    if (latestTask?.request_id === message.request_id && latestTask.status === "CANCELLED") {
      return bossSearchCancelledResult(latestTask, capture.jobs);
    }
    const taskForRepair = latestTask?.request_id === message.request_id ? latestTask : task;
    task = await persistBossJobs(taskForRepair, capture.page_url, capture.jobs, capture.jobs.length, capture.page_state);
    if (task.status === "CANCELLED" || cancelledBossSearchRequests.has(message.request_id)) {
      const cancelled = await getStoredBossSearch();
      return bossSearchCancelledResult(cancelled?.request_id === message.request_id ? cancelled : task, capture.jobs);
    }
    const finishedAt = new Date().toISOString();
    const waitingForUser = !capture.success && RESUMABLE_BOSS_SEARCH_STATES.has(capture.page_state);
    task = {
      ...task,
      status: capture.success ? "COMPLETED" : waitingForUser ? "WAITING_FOR_USER" : "FAILED",
      page_url: capture.page_url,
      page_state: capture.page_state,
      error: capture.error,
      updated_at: finishedAt,
      ...(waitingForUser ? { finished_at: undefined } : { finished_at: finishedAt }),
    };
    await storeBossSearch(task);
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_RESULT",
      request_id: message.request_id,
      success: capture.success,
      page_url: capture.page_url,
      jobs: capture.jobs.slice(0, maxJobs),
      page_state: capture.page_state,
      background_task: task,
      error: capture.error,
    };
  } catch (error) {
    const stored = await getStoredBossSearch();
    if (stored?.request_id === message.request_id && stored.status === "CANCELLED") {
      return bossSearchCancelledResult(stored);
    }
    if (task) {
      const failedAt = new Date().toISOString();
      task = {
        ...task,
        status: "FAILED",
        error: error instanceof Error ? error.message : "BOSS 搜索采集失败",
        updated_at: failedAt,
        finished_at: failedAt,
      };
      await storeBossSearch(task);
    }
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_RESULT",
      request_id: message.request_id,
      success: false,
      page_url: "",
      jobs: [],
      page_state: "UNKNOWN_STATE",
      background_task: task ?? undefined,
      error: error instanceof Error ? error.message : "BOSS 搜索采集失败",
    };
  } finally {
    activeSearchOrigins.delete(message.request_id);
  }
}

async function resumeBossSearch(
  message: BossSearchResumeRequest,
  originTabId?: number,
): Promise<BossBridgeResponse> {
  let task = await getStoredBossSearch();
  if (!task || task.request_id !== message.request_id) {
    return bossSearchFailure(message.request_id, "没有找到可继续的 BOSS 采集任务");
  }
  if (task.status !== "WAITING_FOR_USER") {
    return bossSearchFailure(message.request_id, `当前采集任务状态为 ${task.status}，不能继续` , task);
  }
  cancelledBossSearchRequests.delete(task.request_id);
  if (originTabId !== undefined) activeSearchOrigins.set(task.request_id, originTabId);

  try {
    const tabId = await resolveBossSearchTab(task);
    task = {
      ...task,
      status: "RUNNING",
      tab_id: tabId,
      error: undefined,
      finished_at: undefined,
      updated_at: new Date().toISOString(),
    };
    await storeBossSearch(task);

    const capture = await captureVisibleJobs(tabId, task.target_count, task.request_id);
    const latestTask = await getStoredBossSearch();
    if (latestTask?.request_id === task.request_id && latestTask.status === "CANCELLED") {
      return bossSearchCancelledResult(latestTask, capture.jobs);
    }
    const taskForRepair = latestTask?.request_id === task.request_id ? latestTask : task;
    task = await persistBossJobs(
      taskForRepair,
      capture.page_url,
      capture.jobs,
      capture.jobs.length,
      capture.page_state,
    );
    if (task.status === "CANCELLED" || cancelledBossSearchRequests.has(message.request_id)) {
      const cancelled = await getStoredBossSearch();
      return bossSearchCancelledResult(cancelled?.request_id === message.request_id ? cancelled : task, capture.jobs);
    }
    const finishedAt = new Date().toISOString();
    const waitingForUser = !capture.success && RESUMABLE_BOSS_SEARCH_STATES.has(capture.page_state);
    task = {
      ...task,
      status: capture.success ? "COMPLETED" : waitingForUser ? "WAITING_FOR_USER" : "FAILED",
      page_url: capture.page_url,
      page_state: capture.page_state,
      error: capture.error,
      updated_at: finishedAt,
      ...(waitingForUser ? { finished_at: undefined } : { finished_at: finishedAt }),
    };
    await storeBossSearch(task);
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_RESULT",
      request_id: task.request_id,
      success: capture.success,
      page_url: capture.page_url,
      jobs: capture.jobs.slice(0, task.target_count),
      page_state: capture.page_state,
      background_task: task,
      error: capture.error,
    };
  } catch (error) {
    const stored = await getStoredBossSearch();
    if (stored?.request_id === message.request_id && stored.status === "CANCELLED") {
      return bossSearchCancelledResult(stored);
    }
    const failedAt = new Date().toISOString();
    task = {
      ...task,
      status: "FAILED",
      error: error instanceof Error ? error.message : "BOSS 采集恢复失败",
      updated_at: failedAt,
      finished_at: failedAt,
    };
    await storeBossSearch(task);
    return bossSearchFailure(message.request_id, task.error ?? "BOSS 采集恢复失败", task);
  } finally {
    activeSearchOrigins.delete(message.request_id);
  }
}

async function cancelBossSearch(message: BossSearchCancelRequest): Promise<BossBridgeResponse> {
  const task = await getStoredBossSearch();
  if (!task || task.request_id !== message.request_id) {
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_CANCEL_RESULT",
      request_id: message.request_id,
      success: false,
      task: null,
      error: "没有找到可停止的 BOSS 职位采集任务",
    };
  }
  if (task.status === "CANCELLED") {
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_CANCEL_RESULT",
      request_id: message.request_id,
      success: true,
      task,
    };
  }
  if (task.status !== "RUNNING" && task.status !== "WAITING_FOR_USER") {
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_CANCEL_RESULT",
      request_id: message.request_id,
      success: false,
      task,
      error: `当前采集任务状态为 ${task.status}，无需停止`,
    };
  }

  cancelledBossSearchRequests.add(task.request_id);
  const stoppedAt = new Date().toISOString();
  const cancelledTask: BossBackgroundSearchTask = {
    ...task,
    status: "CANCELLED",
    error: undefined,
    updated_at: stoppedAt,
    finished_at: stoppedAt,
  };
  // Persist the terminal state before notifying the content script. This makes
  // late progress and completion messages harmless even if the tab is busy.
  await storeBossSearch(cancelledTask);
  if (task.tab_id !== undefined) {
    try {
      await browser.tabs.sendMessage(task.tab_id, {
        type: "CANCEL_BOSS_CAPTURE",
        request_id: task.request_id,
      });
    } catch {
      // The tab may already be closed; the persisted state still prevents any
      // subsequent progress from being imported or marked as completed.
    }
  }
  return {
    source: "careerpilot-extension",
    type: "BOSS_SEARCH_CANCEL_RESULT",
    request_id: message.request_id,
    success: true,
    task: cancelledTask,
  };
}

function bossSearchCancelledResult(
  task: BossBackgroundSearchTask,
  jobs: import("../lib/platforms/boss").BossVisibleJob[] = [],
): BossBridgeResponse {
  return {
    source: "careerpilot-extension",
    type: "BOSS_SEARCH_RESULT",
    request_id: task.request_id,
    success: false,
    page_url: task.page_url,
    jobs,
    page_state: task.page_state,
    background_task: task,
    error: "用户已停止职位采集",
  };
}

function bossSearchFailure(
  requestId: string,
  error: string,
  task?: BossBackgroundSearchTask,
): BossBridgeResponse {
  return {
    source: "careerpilot-extension",
    type: "BOSS_SEARCH_RESULT",
    request_id: requestId,
    success: false,
    page_url: task?.page_url ?? "",
    jobs: [],
    page_state: task?.page_state ?? "UNKNOWN_STATE",
    background_task: task,
    error,
  };
}

async function resolveBossSearchTab(task: BossBackgroundSearchTask): Promise<number> {
  if (task.tab_id !== undefined) {
    try {
      const tab = await browser.tabs.get(task.tab_id);
      if (tab.id !== undefined) {
        await ensureBossSearchPage(tab.id, task);
        return tab.id;
      }
    } catch {
      // The original visible tab was closed; recreate the search below.
    }
  }
  const tab = await browser.tabs.create({
    active: true,
    url: buildBossSearchUrl(task.requirements, task.city),
  });
  if (!tab.id) throw new Error("无法恢复 BOSS 搜索标签页");
  await waitForTabComplete(tab.id);
  return tab.id;
}

async function activateVisibleTab(tabId: number): Promise<void> {
  const tab = await browser.tabs.update(tabId, { active: true });
  if (!tab) return;
  if (tab.windowId !== undefined && browser.windows?.update) {
    await browser.windows.update(tab.windowId, { focused: true });
  }
}

async function ensureBossSearchPage(tabId: number, task: BossBackgroundSearchTask): Promise<void> {
  const tab = await browser.tabs.get(tabId);
  if (tab.url && matchesBossJobSearch(tab.url, task.requirements, task.city)) {
    if (tab.status !== "complete") await waitForTabComplete(tabId);
    return;
  }
  await browser.tabs.update(tabId, {
    url: buildBossSearchUrl(task.requirements, task.city),
  });
  await waitForTabComplete(tabId);
}

async function forwardBossSearchProgress(message: BossCaptureProgress): Promise<void> {
  const stored = await getStoredBossSearch();
  if (!stored || stored.request_id !== message.request_id || stored.status !== "RUNNING") return;
  let task = stored;
  try {
    task = await persistBossJobs(
      stored,
      message.page_url,
      message.jobs,
      message.collected_count,
      message.page_state,
    );
  } catch (error) {
    task = {
      ...stored,
      collected_count: message.collected_count,
      page_url: message.page_url,
      page_state: message.page_state,
      error: `增量入库失败，将在任务结束时重试：${error instanceof Error ? error.message : "未知错误"}`,
      updated_at: new Date().toISOString(),
    };
    await storeBossSearch(task);
  }
  const originTabId = activeSearchOrigins.get(message.request_id);
  if (originTabId === undefined) return;
  try {
    await browser.tabs.sendMessage(originTabId, {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_PROGRESS",
      request_id: message.request_id,
      page_url: message.page_url,
      jobs: message.jobs,
      collected_count: message.collected_count,
      target_count: message.target_count,
      page_state: message.page_state,
      background_task: task,
    });
  } catch {
    // The CareerPilot page may have been closed; the visible recruitment tab
    // remains the only page allowed to continue the collection.
  }
}

async function getStoredBossSearch(): Promise<BossBackgroundSearchTask | null> {
  const stored = await browser.storage.local.get(BOSS_SEARCH_STORAGE_KEY);
  const value = stored[BOSS_SEARCH_STORAGE_KEY];
  if (!value || typeof value !== "object") return null;
  const task = value as BossBackgroundSearchTask;
  if (task.status === "FAILED" && RESUMABLE_BOSS_SEARCH_STATES.has(task.page_state)) {
    const recovered: BossBackgroundSearchTask = {
      ...task,
      status: "WAITING_FOR_USER",
      finished_at: undefined,
      updated_at: new Date().toISOString(),
    };
    await storeBossSearch(recovered);
    return recovered;
  }
  return task;
}

async function storeBossSearch(task: BossBackgroundSearchTask): Promise<void> {
  await browser.storage.local.set({ [BOSS_SEARCH_STORAGE_KEY]: task });
}

async function persistBossJobs(
  task: BossBackgroundSearchTask,
  pageUrl: string,
  jobs: import("../lib/platforms/boss").BossVisibleJob[],
  collectedCount: number,
  pageState: import("../lib/platforms/boss").BossPageState,
): Promise<BossBackgroundSearchTask> {
  const currentBeforeImport = await getStoredBossSearch();
  if (currentBeforeImport?.request_id === task.request_id && (
    currentBeforeImport.status === "CANCELLED" || cancelledBossSearchRequests.has(task.request_id)
  )) {
    return currentBeforeImport;
  }
  const knownExternalIds = new Set(task.persisted_jobs.map((job) => job.external_job_id).filter(Boolean));
  const pending = jobs.filter((job) => !knownExternalIds.has(job.external_job_id));
  let persistedJobs = [...task.persisted_jobs];
  let createdCount = task.created_count;
  let updatedCount = task.updated_count;

  for (let index = 0; index < pending.length; index += 25) {
    const current = await getStoredBossSearch();
    if (current?.request_id === task.request_id && (
      current.status === "CANCELLED" || cancelledBossSearchRequests.has(task.request_id)
    )) return current;
    const batch = pending.slice(index, index + 25);
    const imported = await importBossJobs(pageUrl, batch);
    const summaries = imported.items.map(toPersistedJobSummary);
    const merged = new Map(persistedJobs.map((job) => [job.id, job]));
    summaries.forEach((job) => merged.set(job.id, job));
    persistedJobs = [...merged.values()];
    createdCount += imported.created;
    updatedCount += imported.updated;
    const currentAfterImport = await getStoredBossSearch();
    if (currentAfterImport?.request_id === task.request_id && (
      currentAfterImport.status === "CANCELLED" || cancelledBossSearchRequests.has(task.request_id)
    )) {
      return preserveCancelledImportProgress(
        currentAfterImport,
        pageUrl,
        persistedJobs,
        collectedCount,
        pageState,
        createdCount,
        updatedCount,
      );
    }
  }

  const updated: BossBackgroundSearchTask = {
    ...task,
    collected_count: Math.max(task.collected_count, collectedCount),
    persisted_count: persistedJobs.length,
    created_count: createdCount,
    updated_count: updatedCount,
    detailed_count: persistedJobs.filter((job) => job.description_source === "detail_panel").length,
    page_url: pageUrl || task.page_url,
    page_state: pageState,
    persisted_jobs: persistedJobs,
    error: undefined,
    updated_at: new Date().toISOString(),
  };
  const currentBeforeStore = await getStoredBossSearch();
  if (currentBeforeStore?.request_id === task.request_id && (
    currentBeforeStore.status === "CANCELLED" || cancelledBossSearchRequests.has(task.request_id)
  )) {
    return preserveCancelledImportProgress(
      currentBeforeStore,
      pageUrl,
      persistedJobs,
      collectedCount,
      pageState,
      createdCount,
      updatedCount,
    );
  }
  await storeBossSearch(updated);
  return updated;
}

async function preserveCancelledImportProgress(
  cancelledTask: BossBackgroundSearchTask,
  pageUrl: string,
  persistedJobs: BossPersistedJobSummary[],
  collectedCount: number,
  pageState: import("../lib/platforms/boss").BossPageState,
  createdCount: number,
  updatedCount: number,
): Promise<BossBackgroundSearchTask> {
  const merged = new Map(cancelledTask.persisted_jobs.map((job) => [job.id, job]));
  persistedJobs.forEach((job) => merged.set(job.id, job));
  const jobs = [...merged.values()];
  const stoppedAt = cancelledTask.finished_at ?? new Date().toISOString();
  const preserved: BossBackgroundSearchTask = {
    ...cancelledTask,
    status: "CANCELLED",
    collected_count: Math.max(cancelledTask.collected_count, collectedCount),
    persisted_count: jobs.length,
    created_count: Math.max(cancelledTask.created_count, createdCount),
    updated_count: Math.max(cancelledTask.updated_count, updatedCount),
    detailed_count: jobs.filter((job) => job.description_source === "detail_panel").length,
    page_url: pageUrl || cancelledTask.page_url,
    page_state: pageState,
    persisted_jobs: jobs,
    error: undefined,
    updated_at: new Date().toISOString(),
    finished_at: stoppedAt,
  };
  await storeBossSearch(preserved);
  return preserved;
}

type BossImportResponse = {
  items: Array<{
    id: string;
    external_job_id: string | null;
    title: string;
    location: string | null;
    raw_data: Record<string, unknown>;
  }>;
  created: number;
  updated: number;
};

async function importBossJobs(
  pageUrl: string,
  jobs: import("../lib/platforms/boss").BossVisibleJob[],
): Promise<BossImportResponse> {
  if (!pageUrl || jobs.length === 0) return { items: [], created: 0, updated: 0 };
  const response = await fetch(`${API_BASE_URL}/api/platforms/boss/import-visible`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      page_url: pageUrl,
      captured_at: new Date().toISOString(),
      jobs,
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail || `职位入库失败：${response.status}`);
  }
  return response.json() as Promise<BossImportResponse>;
}

function toPersistedJobSummary(job: BossImportResponse["items"][number]): BossPersistedJobSummary {
  const descriptionSource = job.raw_data.description_source === "detail_panel" ? "detail_panel" : "card_summary";
  return {
    id: job.id,
    external_job_id: job.external_job_id,
    title: job.title,
    location: job.location,
    company_name: typeof job.raw_data.company_name === "string" ? job.raw_data.company_name : null,
    salary_text: typeof job.raw_data.salary_text === "string" ? job.raw_data.salary_text : null,
    description_source: descriptionSource,
  };
}

async function launchBossTaskBatch(message: BossTaskBatchLaunchRequest): Promise<BossBridgeResponse> {
  const responseType = message.type === "BOSS_TASK_BATCH_LAUNCH_REQUEST" ? "BOSS_TASK_BATCH_LAUNCH_RESULT" : "RECRUITMENT_TASK_BATCH_LAUNCH_RESULT";
  try {
    if (message.tasks.length === 0) throw new Error("投递队列为空");
    const queuedIds = new Set(batchQueue.map((item) => item.task_id));
    const accepted: Array<{ task_id: string; url: string }> = [];
    for (const item of message.tasks) {
      const url = new URL(item.url);
      const platform = deliveryPlatform(url.toString());
      if (!platform || (message.type === "BOSS_TASK_BATCH_LAUNCH_REQUEST" && platform !== "boss") || (item.platform && platform !== item.platform) || url.searchParams.get("task") !== item.task_id) {
        throw new Error(`Browser Task ${item.task_id.slice(0, 8)} URL 未通过招聘平台安全校验`);
      }
      if (queuedIds.has(item.task_id) || activeBatchTaskId === item.task_id) continue;
      queuedIds.add(item.task_id);
      accepted.push({ task_id: item.task_id, url: url.toString() });
    }
    batchQueue.push(...accepted);
    await startNextBatchTask();
    return {
      source: "careerpilot-extension",
      type: responseType,
      request_id: message.request_id,
      success: true,
      accepted_count: accepted.length,
    };
  } catch (error) {
    return {
      source: "careerpilot-extension",
      type: responseType,
      request_id: message.request_id,
      success: false,
      accepted_count: 0,
      error: error instanceof Error ? error.message : "招聘平台串行投递队列启动失败",
    };
  }
}

async function startNextBatchTask(): Promise<void> {
  if (activeBatchTaskId || batchQueue.length === 0) return;
  const next = batchQueue[0];
  activeBatchTaskId = next.task_id;
  if (batchTabId !== null) {
    try {
      await browser.tabs.get(batchTabId);
      await browser.tabs.update(batchTabId, { active: true, url: next.url });
      return;
    } catch {
      batchTabId = null;
    }
  }
  try {
    const tab = await browser.tabs.create({ active: true, url: next.url });
    if (!tab.id) throw new Error("无法创建招聘平台串行投递标签页");
    batchTabId = tab.id;
  } catch (error) {
    activeBatchTaskId = null;
    throw error;
  }
}

function finishBatchTask(taskId: string): void {
  if (activeBatchTaskId !== taskId) return;
  sockets.get(taskId)?.close();
  sockets.delete(taskId);
  activeTabs.delete(taskId);
  if (batchQueue[0]?.task_id === taskId) batchQueue.shift();
  activeBatchTaskId = null;
  globalThis.setTimeout(() => void startNextBatchTask(), 600);
}

function cancelBatchTasks(taskIds: string[]): void {
  const cancelled = new Set(taskIds);
  for (let index = batchQueue.length - 1; index >= 0; index -= 1) {
    if (cancelled.has(batchQueue[index].task_id)) batchQueue.splice(index, 1);
  }
  for (const taskId of cancelled) {
    sockets.get(taskId)?.close();
    sockets.delete(taskId);
    activeTabs.delete(taskId);
  }
  if (activeBatchTaskId && cancelled.has(activeBatchTaskId)) activeBatchTaskId = null;
  globalThis.setTimeout(() => void startNextBatchTask(), 100);
}

async function captureVisibleJobs(
  tabId: number,
  maxJobs: number,
  requestId: string,
): Promise<BossCaptureResponse> {
  let lastResult: BossCaptureResponse | null = null;
  let lastError: unknown = null;
  const terminalStates = new Set(["CAPTCHA", "LOGIN_REQUIRED", "PLATFORM_LIMIT", "RISK_CONTROL", "DOM_CHANGED", "TAB_HIDDEN"]);
  // Activate once so the first result surface can load. Once cards are
  // available, the content script can keep parsing without misclassifying a
  // complete page as TAB_HIDDEN. A tab hidden before initial load still pauses.
  await activateVisibleTab(tabId);
  for (let attempt = 0; attempt < 24; attempt += 1) {
    const task = await getStoredBossSearch();
    if (task?.request_id === requestId && (
      task.status === "CANCELLED" || cancelledBossSearchRequests.has(requestId)
    )) {
      return {
        type: "BOSS_CAPTURE_RESULT",
        success: false,
        cancelled: true,
        page_url: task.page_url,
        jobs: [],
        page_state: task.page_state,
        error: "用户已停止职位采集",
      };
    }
    if (!task || task.request_id !== requestId) {
      throw new Error("BOSS 采集任务状态已丢失，无法验证搜索页面");
    }
    await ensureBossSearchPage(tabId, task);
    await new Promise((resolve) => globalThis.setTimeout(resolve, attempt === 0 ? 900 : 1000));
    try {
      const result = await browser.tabs.sendMessage(tabId, {
        type: "CAPTURE_BOSS_VISIBLE",
        request_id: requestId,
        max_jobs: maxJobs,
        include_details: true,
        require_search_page: true,
      }) as BossCaptureResponse;
      lastResult = result;
      if (result.cancelled) return result;
      if (!result.success && terminalStates.has(result.page_state)) return result;
      if (!result.success && result.error?.includes("empty=true")) return result;
      if (result.success && result.jobs.length > 0) return result;
    } catch (error) {
      lastError = error;
    }
  }
  if (lastResult) {
    return {
      ...lastResult,
      success: false,
      error: `等待 BOSS 搜索结果约 24 秒后仍未识别到职位。${lastResult.error || "请确认页面停留在职位搜索结果，并检查是否出现登录或验证提示。"}`,
    };
  }
  throw lastError instanceof Error ? lastError : new Error("无法连接 BOSS 页面内容脚本");
}

async function launchBossTask(message: BossTaskLaunchRequest): Promise<BossBridgeResponse> {
  try {
    const url = new URL(message.url);
    if (!isBossPageUrl(url.toString()) || url.searchParams.get("task") !== message.task_id) {
      throw new Error("Browser Task URL 未通过 BOSS 安全校验");
    }
    await browser.tabs.create({ active: true, url: url.toString() });
    return {
      source: "careerpilot-extension",
      type: "BOSS_TASK_LAUNCH_RESULT",
      request_id: message.request_id,
      task_id: message.task_id,
      success: true,
    };
  } catch (error) {
    return {
      source: "careerpilot-extension",
      type: "BOSS_TASK_LAUNCH_RESULT",
      request_id: message.request_id,
      task_id: message.task_id,
      success: false,
      error: error instanceof Error ? error.message : "Browser Task 启动失败",
    };
  }
}


function connectTask(taskId: string, tabId: number) {
  if (sockets.has(taskId)) return;
  const socket = new WebSocket(`${API_WS_BASE}${taskId}`);
  sockets.set(taskId, socket);
  socket.addEventListener("open", () => socket.send(JSON.stringify({ type: "EXTENSION_HELLO", extension_version: "phase8", tab_url: "" })));
  socket.addEventListener("message", async (event) => {
    let message: ActionMessage | null = null;
    try {
      const incoming = JSON.parse(String(event.data)) as ActionMessage | BrowserTaskLifecycleMessage | BrowserTaskBatchLifecycleMessage;
      if (incoming.type === "TASK_BATCH_CANCELLED") {
        cancelBatchTasks(incoming.task_ids);
        return;
      }
      if (["TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"].includes(incoming.type)) {
        finishBatchTask(incoming.task_id);
        return;
      }
      message = incoming as ActionMessage;
      if (message.type !== "ACTION" && message.type !== "REQUEST_USER_ACTION") return;
      if (message.action.action === "NAVIGATE" && message.action.url) {
        const currentTab = await browser.tabs.get(tabId);
        if (currentTab.url !== message.action.url) {
          await browser.tabs.update(tabId, { url: message.action.url });
        }
        await waitForTabComplete(tabId);
        socket.send(JSON.stringify({
          type: "ACTION_RESULT",
          action_id: message.action.id,
          success: true,
          data: { page_url: message.action.url, platform: deliveryPlatform(message.action.url) },
          page_state: "NAVIGATED",
        }));
        return;
      }
      await browser.tabs.sendMessage(tabId, message);
    } catch (error) {
      if (!message || message.type === "REQUEST_USER_ACTION") return;
      socket.send(JSON.stringify({
        type: "ACTION_RESULT",
        action_id: message.action.id,
        success: false,
        error: error instanceof Error ? error.message : "无法在招聘页面执行浏览器动作",
      }));
    }
  });
  socket.addEventListener("close", () => sockets.delete(taskId));
}
