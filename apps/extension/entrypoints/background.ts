import { buildBossSearchUrl, isBossPageUrl } from "../lib/platforms/boss";
import type {
  ActionMessage,
  ActionResultMessage,
  BossTaskBatchLaunchRequest,
  BossBridgeRequest,
  BossBridgeResponse,
  BossCaptureResponse,
  BossSearchRequest,
  BossTaskLaunchRequest,
  BrowserTaskBatchLifecycleMessage,
  BrowserTaskLifecycleMessage,
} from "../lib/protocol";

const API_WS_BASE = "ws://localhost:8010/api/browser-tasks/ws/";
const sockets = new Map<string, WebSocket>();
const activeTabs = new Map<string, number>();
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
    message: ActionResultMessage | BossBridgeRequest,
    sender,
  ): Promise<BossBridgeResponse | undefined> => {
    if (message.type === "BOSS_SEARCH_REQUEST") return runBossSearch(message);
    if (message.type === "BOSS_TASK_LAUNCH_REQUEST") return launchBossTask(message);
    if (message.type === "BOSS_TASK_BATCH_LAUNCH_REQUEST") return launchBossTaskBatch(message);
    if (message.type !== "ACTION_RESULT") return;
    const tabId = sender.tab?.id;
    const taskId = [...activeTabs.entries()].find(([, activeTabId]) => activeTabId === tabId)?.[0];
    if (!taskId) return;
    sockets.get(taskId)?.send(JSON.stringify(message));
  });
});

async function runBossSearch(message: BossSearchRequest): Promise<BossBridgeResponse> {
  try {
    const requirements = message.payload.requirements.trim();
    const maxJobs = Math.min(Math.max(message.payload.max_jobs, 1), 50);
    if (!requirements) throw new Error("请填写岗位要求");
    const tab = await browser.tabs.create({
      active: false,
      url: buildBossSearchUrl(requirements, message.payload.city),
    });
    if (!tab.id) throw new Error("无法创建 BOSS 搜索标签页");
    await waitForTabComplete(tab.id);
    const capture = await captureVisibleJobs(tab.id, maxJobs);
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_RESULT",
      request_id: message.request_id,
      success: capture.success,
      page_url: capture.page_url,
      jobs: capture.jobs.slice(0, maxJobs),
      page_state: capture.page_state,
      error: capture.error,
    };
  } catch (error) {
    return {
      source: "careerpilot-extension",
      type: "BOSS_SEARCH_RESULT",
      request_id: message.request_id,
      success: false,
      page_url: "",
      jobs: [],
      page_state: "UNKNOWN_STATE",
      error: error instanceof Error ? error.message : "BOSS 搜索采集失败",
    };
  }
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
      await browser.tabs.update(batchTabId, { active: true, url: next.url });
      return;
    } catch {
      batchTabId = null;
    }
  }
  const tab = await browser.tabs.create({ active: true, url: next.url });
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

async function captureVisibleJobs(tabId: number, maxJobs: number): Promise<BossCaptureResponse> {
  let lastResult: BossCaptureResponse | null = null;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    await new Promise((resolve) => globalThis.setTimeout(resolve, attempt === 0 ? 800 : 750));
    try {
      const result = await browser.tabs.sendMessage(tabId, {
        type: "CAPTURE_BOSS_VISIBLE",
        max_jobs: maxJobs,
        include_details: true,
      }) as BossCaptureResponse;
      lastResult = result;
      if (!result.success && result.page_state !== "UNKNOWN_STATE") return result;
      if (result.success && result.jobs.length > 0) return result;
    } catch (error) {
      lastError = error;
    }
  }
  if (lastResult) {
    return {
      ...lastResult,
      success: false,
      error: "BOSS 页面已加载，但没有识别到新版职位卡片；请刷新页面后重试。",
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
