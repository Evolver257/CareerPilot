import { buildBossSearchUrl, isBossPageUrl, MAX_BOSS_BATCH_JOBS } from "../lib/platforms/boss";
import type {
  ActionMessage,
  ActionResultMessage,
  BossTaskBatchLaunchRequest,
  BossBackgroundSearchTask,
  BossBridgeRequest,
  BossBridgeResponse,
  BossCaptureProgress,
  BossCaptureResponse,
  BossPersistedJobSummary,
  BossSearchRequest,
  BossSearchResumeRequest,
  BossTaskLaunchRequest,
  BrowserTaskBatchLifecycleMessage,
  BrowserTaskLifecycleMessage,
} from "../lib/protocol";

const API_WS_BASE = "ws://localhost:8010/api/browser-tasks/ws/";
const API_BASE_URL = "http://localhost:8010";
const BOSS_SEARCH_STORAGE_KEY = "careerpilot_boss_background_search";
const RESUMABLE_BOSS_SEARCH_STATES = new Set(["CAPTCHA", "LOGIN_REQUIRED", "RISK_CONTROL"]);
const sockets = new Map<string, WebSocket>();
const activeTabs = new Map<string, number>();
const activeSearchOrigins = new Map<string, number>();
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
    message: ActionResultMessage | BossBridgeRequest | BossCaptureProgress,
    sender,
  ): Promise<BossBridgeResponse | undefined> => {
    if (message.type === "BOSS_CAPTURE_PROGRESS") {
      await forwardBossSearchProgress(message);
      return;
    }
    if (message.type === "BOSS_SEARCH_REQUEST") return runBossSearch(message, sender.tab?.id);
    if (message.type === "BOSS_SEARCH_RESUME_REQUEST") return resumeBossSearch(message, sender.tab?.id);
    if (message.type === "BOSS_SEARCH_STATUS_REQUEST") {
      return {
        source: "careerpilot-extension",
        type: "BOSS_SEARCH_STATUS_RESULT",
        request_id: message.request_id,
        task: await getStoredBossSearch(),
      };
    }
    if (message.type === "BOSS_TASK_LAUNCH_REQUEST") return launchBossTask(message);
    if (message.type === "BOSS_TASK_BATCH_LAUNCH_REQUEST") return launchBossTaskBatch(message);
    if (message.type !== "ACTION_RESULT") return;
    const tabId = sender.tab?.id;
    const taskId = [...activeTabs.entries()].find(([, activeTabId]) => activeTabId === tabId)?.[0];
    if (!taskId) return;
    sockets.get(taskId)?.send(JSON.stringify(message));
  });
});

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
      throw new Error("已有 BOSS 后台采集任务正在运行，请等待其完成后再启动新任务");
    }
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
      active: false,
      url: buildBossSearchUrl(requirements, message.payload.city),
    });
    if (!tab.id) throw new Error("无法创建 BOSS 搜索标签页");
    task = { ...task, tab_id: tab.id, updated_at: new Date().toISOString() };
    await storeBossSearch(task);
    await waitForTabComplete(tab.id);
    const capture = await captureVisibleJobs(tab.id, maxJobs, message.request_id);
    const latestTask = await getStoredBossSearch();
    const taskForRepair = latestTask?.request_id === message.request_id ? latestTask : task;
    task = await persistBossJobs(taskForRepair, capture.page_url, capture.jobs, capture.jobs.length, capture.page_state);
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
    const taskForRepair = latestTask?.request_id === task.request_id ? latestTask : task;
    task = await persistBossJobs(
      taskForRepair,
      capture.page_url,
      capture.jobs,
      capture.jobs.length,
      capture.page_state,
    );
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
      if (tab.id !== undefined && tab.url && isBossPageUrl(tab.url)) return tab.id;
    } catch {
      // The original background tab was closed; recreate the search below.
    }
  }
  const tab = await browser.tabs.create({
    active: false,
    url: task.page_url && isBossPageUrl(task.page_url)
      ? task.page_url
      : buildBossSearchUrl(task.requirements, task.city),
  });
  if (!tab.id) throw new Error("无法恢复 BOSS 搜索标签页");
  await waitForTabComplete(tab.id);
  return tab.id;
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
    // The CareerPilot page may have been closed while the background tab continues safely.
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
  const knownExternalIds = new Set(task.persisted_jobs.map((job) => job.external_job_id).filter(Boolean));
  const pending = jobs.filter((job) => !knownExternalIds.has(job.external_job_id));
  let persistedJobs = [...task.persisted_jobs];
  let createdCount = task.created_count;
  let updatedCount = task.updated_count;

  for (let index = 0; index < pending.length; index += 25) {
    const batch = pending.slice(index, index + 25);
    const imported = await importBossJobs(pageUrl, batch);
    const summaries = imported.items.map(toPersistedJobSummary);
    const merged = new Map(persistedJobs.map((job) => [job.id, job]));
    summaries.forEach((job) => merged.set(job.id, job));
    persistedJobs = [...merged.values()];
    createdCount += imported.created;
    updatedCount += imported.updated;
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
  await storeBossSearch(updated);
  return updated;
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
    body: JSON.stringify({ page_url: pageUrl, jobs }),
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
  try {
    if (message.tasks.length === 0) throw new Error("投递队列为空");
    const queuedIds = new Set(batchQueue.map((item) => item.task_id));
    const accepted: Array<{ task_id: string; url: string }> = [];
    for (const item of message.tasks) {
      const url = new URL(item.url);
      if (!isBossPageUrl(url.toString()) || url.searchParams.get("task") !== item.task_id) {
        throw new Error(`Browser Task ${item.task_id.slice(0, 8)} URL 未通过 BOSS 安全校验`);
      }
      if (queuedIds.has(item.task_id) || activeBatchTaskId === item.task_id) continue;
      queuedIds.add(item.task_id);
      accepted.push({ task_id: item.task_id, url: url.toString() });
    }
    batchQueue.push(...accepted);
    await startNextBatchTask();
    return {
      source: "careerpilot-extension",
      type: "BOSS_TASK_BATCH_LAUNCH_RESULT",
      request_id: message.request_id,
      success: true,
      accepted_count: accepted.length,
    };
  } catch (error) {
    return {
      source: "careerpilot-extension",
      type: "BOSS_TASK_BATCH_LAUNCH_RESULT",
      request_id: message.request_id,
      success: false,
      accepted_count: 0,
      error: error instanceof Error ? error.message : "BOSS 串行投递队列启动失败",
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
      await browser.tabs.update(batchTabId, { url: next.url });
      return;
    } catch {
      batchTabId = null;
    }
  }
  const tab = await browser.tabs.create({ active: false, url: next.url });
  if (!tab.id) {
    activeBatchTaskId = null;
    throw new Error("无法创建 BOSS 串行投递标签页");
  }
  batchTabId = tab.id;
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
  const terminalStates = new Set(["CAPTCHA", "LOGIN_REQUIRED", "PLATFORM_LIMIT", "RISK_CONTROL", "DOM_CHANGED"]);
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await new Promise((resolve) => globalThis.setTimeout(resolve, attempt === 0 ? 900 : 1000));
    try {
      const result = await browser.tabs.sendMessage(tabId, {
        type: "CAPTURE_BOSS_VISIBLE",
        request_id: requestId,
        max_jobs: maxJobs,
        include_details: true,
      }) as BossCaptureResponse;
      lastResult = result;
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

async function waitForTabComplete(tabId: number): Promise<void> {
  const tab = await browser.tabs.get(tabId);
  if (tab.status === "complete") return;
  await new Promise<void>((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => {
      browser.tabs.onUpdated.removeListener(listener);
      reject(new Error("BOSS 页面加载超时，请检查登录状态或网络"));
    }, 30_000);
    const listener = (updatedTabId: number, changeInfo: { status?: string }) => {
      if (updatedTabId !== tabId || changeInfo.status !== "complete") return;
      globalThis.clearTimeout(timeout);
      browser.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    browser.tabs.onUpdated.addListener(listener);
  });
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
          data: { page_url: message.action.url, platform: "boss" },
          page_state: "NAVIGATED",
        }));
        return;
      }
      await browser.tabs.sendMessage(tabId, message);
    } catch (error) {
      if (!message) return;
      socket.send(JSON.stringify({
        type: "ACTION_RESULT",
        action_id: message.action.id,
        success: false,
        error: error instanceof Error ? error.message : "无法在 BOSS 页面执行浏览器动作",
      }));
    }
  });
  socket.addEventListener("close", () => sockets.delete(taskId));
}
