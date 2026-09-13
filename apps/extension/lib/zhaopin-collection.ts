import { waitForTabComplete } from "./browser-navigation";
import type { CollectedJob, ZhaopinCollectionRequest, ZhaopinCollectionResponse, ZhaopinCollectionTask } from "./collection-types";
import { isZhaopinSearchUrl, mergeZhaopinDetail, zhaopinJobId, type ZhaopinPageState, type ZhaopinVisibleJob } from "./platforms/zhaopin";
import type { ZhaopinCaptureResponse } from "./protocol";

const KEY = "careerpilot_zhaopin_background_search";
const API = "http://localhost:8010";
const HUMAN_STATES = new Set(["CAPTCHA", "LOGIN_REQUIRED", "RISK_CONTROL", "PLATFORM_LIMIT", "TAB_HIDDEN"]);
let activeRequest: string | null = null;
let commands = Promise.resolve();
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const read = async (): Promise<ZhaopinCollectionTask | null> => (await browser.storage.local.get(KEY))[KEY] as ZhaopinCollectionTask ?? null;
const save = async (task: ZhaopinCollectionTask) => {
  task.updated_at = new Date().toISOString();
  await browser.storage.local.set({ [KEY]: task });
};
class PageError extends Error {
  constructor(message: string, public state: ZhaopinPageState) { super(message); }
}
async function api<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(API + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload), signal: AbortSignal.timeout(25_000),
  });
  if (!response.ok) throw new Error("保存或评分失败（HTTP " + response.status + "），已保存的岗位不会丢失");
  return response.json() as Promise<T>;
}

// Short commands are serialized; collection itself runs independently of the web tab.
export function handleZhaopinCollection(message: ZhaopinCollectionRequest): Promise<ZhaopinCollectionResponse> {
  return inOrder(() => handle(message));
}
function inOrder<T>(operation: () => Promise<T>): Promise<T> {
  const result = commands.then(operation);
  commands = result.then(() => undefined, () => undefined);
  return result;
}
async function handle(message: ZhaopinCollectionRequest): Promise<ZhaopinCollectionResponse> {
  const response = (task: ZhaopinCollectionTask | null, error?: string): ZhaopinCollectionResponse => ({
    source: "careerpilot-extension", type: "ZHAOPIN_TASK_STATE", request_id: message.request_id, task, error,
  });
  let task = await read();
  if (task?.status === "RUNNING" && activeRequest !== task.request_id) {
    task.status = "INTERRUPTED";
    task.error = "扩展曾重启，已保留进度；点击继续采集恢复";
    await save(task);
  }
  if (message.type === "ZHAOPIN_SEARCH_STATUS_REQUEST") return response(task);
  if (message.type === "ZHAOPIN_SEARCH_OPEN_REQUEST") {
    if (!task || task.request_id !== message.request_id) return response(task, "未找到采集任务");
    const tabId = task.active_url && zhaopinJobId(task.active_url) ? task.detail_tab_id : task.search_tab_id;
    if (tabId === undefined) return response(task, "采集页面尚未打开");
    try {
      const tab = await browser.tabs.update(tabId, { active: true });
      if (tab?.windowId !== undefined) await browser.windows.update(tab.windowId, { focused: true });
      return response(task);
    } catch { return response(task, "原采集标签页已关闭，点击继续采集可重新打开"); }
  }
  if (message.type === "ZHAOPIN_SEARCH_CANCEL_REQUEST") {
    if (!task || task.request_id !== message.request_id) return response(task, "任务编号不匹配");
    if (["RUNNING", "WAITING_FOR_USER", "INTERRUPTED"].includes(task.status)) {
      task.status = "CANCELLED"; task.error = undefined; await save(task);
    }
    return response(task);
  }
  if (activeRequest) return response(task, "已有智联采集正在处理，请稍后再试");
  if (message.type === "ZHAOPIN_SEARCH_REQUEST") {
    const payload = message.payload;
    if (!payload || !isZhaopinSearchUrl(payload.search_url)) return response(task, "请提供智联 /sou/ 或 /web/search/ 搜索结果页地址");
    if (task && ["WAITING_FOR_USER", "INTERRUPTED"].includes(task.status)) return response(task, "请先继续或停止上一轮采集");
    const now = new Date().toISOString();
    task = {
      request_id: message.request_id, status: "RUNNING",
      search_url: payload.search_url, page_url: payload.search_url,
      target_count: Math.min(200, Math.max(1, Math.floor(payload.max_jobs) || 20)),
      quick_score_threshold: Math.min(100, Math.max(0, payload.quick_score_threshold || 0)),
      resume_id: payload.resume_id, jobs: [], pending: [], page_state: "UNKNOWN_STATE",
      created_count: 0, updated_count: 0, started_at: now, updated_at: now,
    };
  } else {
    if (!task || task.request_id !== message.request_id || !["WAITING_FOR_USER", "INTERRUPTED", "FAILED"].includes(task.status)) {
      return response(task, "当前任务不可恢复");
    }
    task.status = "RUNNING"; task.error = undefined;
  }
  await save(task);
  activeRequest = task.request_id;
  void execute(task.request_id).finally(() => { activeRequest = null; });
  return response(task);
}
async function current(id: string): Promise<ZhaopinCollectionTask | null> {
  const task = await read();
  return task?.request_id === id && task.status === "RUNNING" ? task : null;
}
async function checkpoint(id: string, patch: Partial<ZhaopinCollectionTask>): Promise<boolean> {
  return inOrder(async () => {
  // Keep cancellation authoritative even when an in-flight import has just completed.
  const latest = await read();
  if (!latest || latest.request_id !== id) return false;
  await save({ ...latest, ...patch, status: latest.status === "CANCELLED" ? "CANCELLED" : patch.status ?? latest.status });
  return latest.status === "RUNNING";
  });
}
async function ensureTab(tabId: number | undefined, url: string): Promise<number> {
  if (tabId !== undefined) {
    let exists = false;
    try {
      await browser.tabs.get(tabId); exists = true;
    } catch { /* Recreate only our missing/closed collection tab. */ }
    if (exists) {
      if ((await browser.tabs.get(tabId)).url !== url) await browser.tabs.update(tabId, { active: true, url });
      await activateVisibleTab(tabId);
      await waitForTabComplete(tabId); return tabId;
    }
  }
  const created = await browser.tabs.create({ active: true, url });
  if (created.id === undefined) throw new Error("无法创建采集标签页");
  await waitForTabComplete(created.id); return created.id;
}
async function activateVisibleTab(tabId: number): Promise<void> {
  const tab = await browser.tabs.update(tabId, { active: true });
  if (!tab) return;
  if (tab.windowId !== undefined && browser.windows?.update) {
    await browser.windows.update(tab.windowId, { focused: true });
  }
}
async function snapshot(tabId: number, requestId: string): Promise<ZhaopinCaptureResponse> {
  let last: ZhaopinCaptureResponse | undefined;
  for (let attempt = 0; attempt < 12; attempt++) {
    if (!await current(requestId)) throw new Error("采集已停止");
    try {
      last = await browser.tabs.sendMessage(tabId, { type: "CAPTURE_ZHAOPIN_VISIBLE", request_id: requestId, max_jobs: 200 }) as ZhaopinCaptureResponse;
      if (last && HUMAN_STATES.has(last.page_state)) throw new PageError(last.error || "请在智联页面完成人工验证后继续", last.page_state);
      if (last?.success || last?.empty) return last;
    } catch (error) { if (error instanceof PageError) throw error; }
    await delay(650);
  }
  throw new PageError(last?.error || "页面加载后未找到完整职位内容，请打开采集页面检查后重试", "DOM_CHANGED");
}
async function execute(id: string): Promise<void> {
  try {
    let task = await current(id); if (!task) return;
    const searchId = await ensureTab(task.search_tab_id, task.page_url);
    if (!await checkpoint(id, { search_tab_id: searchId })) return;
    while ((task = await current(id))) {
      // An extension restart can occur after the import checkpoint but before scoring.
      const unscored = task.resume_id && task.jobs.find((job) => job.score === undefined && !job.score_error);
      if (unscored) {
        try {
          const scores = await api<{ items: Array<{ score: number; score_status: CollectedJob["score_status"]; score_confidence: number }> }>("/api/jobs/quick-score", { job_ids: [unscored.id], resume_id: task.resume_id });
          if (!scores.items[0]) throw new Error("评分结果为空");
          unscored.score = scores.items[0].score;
          unscored.score_status = scores.items[0].score_status;
          unscored.score_confidence = scores.items[0].score_confidence;
        } catch { unscored.score_error = "快速评分失败，岗位已保存，请在智能匹配中重新评分"; }
        if (!await checkpoint(id, { jobs: task.jobs })) return;
        continue;
      }
      if (task.jobs.length >= task.target_count) {
        await checkpoint(id, { status: "COMPLETED", end_reason: "已达到采集数量", error: undefined }); return;
      }
      if (task.pending.length === 0) {
        await checkpoint(id, { active_url: task.page_url });
        const page = await snapshot(searchId, id);
        const known = new Set(task.jobs.map((job) => job.external_job_id));
        const pending = page.jobs.filter((job) => !known.has(job.external_job_id)).slice(0, task.target_count - task.jobs.length);
        const signature = page.jobs.map((job) => job.external_job_id).join(",");
        if (pending.length) {
          if (!await checkpoint(id, { pending, page_signature: signature, page_url: page.page_url, page_state: "READY" })) return;
          continue;
        }
        if (page.empty) {
          await checkpoint(id, { status: "COMPLETED", end_reason: "当前条件没有更多岗位" }); return;
        }
        const next = await browser.tabs.sendMessage(searchId, { type: "ADVANCE_ZHAOPIN_SEARCH" }) as { advanced: boolean; next_url?: string };
        if (!next.advanced) {
          await checkpoint(id, { status: "COMPLETED", end_reason: "已读取到列表末尾；实际岗位数少于设置上限" }); return;
        }
        if (next.next_url) {
          if (!isZhaopinSearchUrl(next.next_url)) throw new Error("下一页地址不属于智联职位搜索页");
          await checkpoint(id, { page_url: next.next_url });
          await browser.tabs.update(searchId, { url: next.next_url });
          await waitForTabComplete(searchId);
        }
        let changed = false;
        for (let attempt = 0; attempt < 8; attempt++) {
          const fresh = await snapshot(searchId, id);
          if (fresh.jobs.map((job) => job.external_job_id).join(",") !== signature) { changed = true; break; }
          await delay(600);
        }
        if (!changed) throw new PageError("翻页后列表未更新，请在搜索页确认是否需要登录或手动加载，然后继续", "DOM_CHANGED");
        continue;
      }
      const card = task.pending[0];
      if (!zhaopinJobId(card.job_url)) throw new Error("列表职位链接无效");
      await checkpoint(id, { active_url: card.job_url });
      const detailId = await ensureTab(task.detail_tab_id, card.job_url);
      if (!await checkpoint(id, { detail_tab_id: detailId })) return;
      const detailPage = await snapshot(detailId, id);
      const detail = detailPage.jobs.find((job) => job.external_job_id === card.external_job_id && job.raw_data.description_source === "detail_page");
      if (!detail) throw new PageError("详情页编号不匹配或完整 JD 尚未显示，已暂停以免保存错误内容", "DOM_CHANGED");
      const job = mergeZhaopinDetail(card, detail);
      if (!await current(id)) return;
      const imported = await api<{ items: Array<{ id: string }>; created: number; updated: number }>("/api/platforms/zhaopin/import-visible", {
        page_url: detailPage.page_url, captured_at: new Date().toISOString(), jobs: [job],
      });
      if (!imported.items[0]) throw new Error("职位保存接口没有返回岗位编号");
      const summary: CollectedJob = {
        id: imported.items[0].id, external_job_id: job.external_job_id, title: job.title,
        location: job.location, company_name: job.company_name, salary_text: job.salary_text, education: job.education,
      };
      const jobs = [...task.jobs, summary];
      if (!await checkpoint(id, {
        jobs, pending: task.pending.slice(1), created_count: task.created_count + imported.created,
        updated_count: task.updated_count + imported.updated, page_state: "READY",
      })) return;
      if (task.resume_id) {
        try {
          const scores = await api<{ items: Array<{ score: number; score_status: CollectedJob["score_status"]; score_confidence: number }> }>("/api/jobs/quick-score", { job_ids: [summary.id], resume_id: task.resume_id });
          if (!scores.items[0]) throw new Error("评分结果为空");
          summary.score = scores.items[0].score;
          summary.score_status = scores.items[0].score_status;
          summary.score_confidence = scores.items[0].score_confidence;
        } catch { summary.score_error = "快速评分失败，岗位已保存，请在智能匹配中重新评分"; }
      }
      if (!await checkpoint(id, { jobs })) return;
      await delay(800);
    }
  } catch (error) {
    if (!await current(id)) return;
    const state = error instanceof PageError ? error.state : "UNKNOWN_STATE";
    await checkpoint(id, {
      status: HUMAN_STATES.has(state) ? "WAITING_FOR_USER" : "FAILED",
      page_state: state, error: error instanceof Error ? error.message : "采集失败，可从已保存进度重试",
    });
  }
}
