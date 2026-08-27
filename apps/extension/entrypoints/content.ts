import { describeBossJobSurface, detectBossPageState, extractVisibleBossJobs, extractVisibleBossJobsWithDetails, isBossPageUrl } from "../lib/platforms/boss";
import {
  findSemanticElement,
  type ActionMessage,
  type ActionResultMessage,
  type BossBridgeRequest,
  type BossBridgeResponse,
  type BossCaptureRequest,
  type BossCaptureProgress,
  type BossCaptureResponse,
  type BossSearchProgress,
} from "../lib/protocol";

export default defineContentScript({
  matches: ["http://localhost:3000/*", "https://www.zhipin.com/*", "https://zhipin.com/*", "https://m.zhipin.com/*"],
  runAt: "document_idle",
  main() {
    if (window.location.origin === "http://localhost:3000") {
      window.addEventListener("message", (event: MessageEvent<unknown>) => {
        if (event.source !== window || !isBossBridgeRequest(event.data)) return;
        if (event.data.type === "BOSS_EXTENSION_PING") {
          window.postMessage(
            {
              source: "careerpilot-extension",
              type: "BOSS_EXTENSION_PONG",
              request_id: event.data.request_id,
              version: "0.2.6",
            },
            window.location.origin,
          );
          return;
        }
        void forwardBridgeRequest(event.data);
      });
    }
    browser.runtime.onMessage.addListener(async (
      message: ActionMessage | BossCaptureRequest | BossSearchProgress,
    ): Promise<ActionResultMessage | BossCaptureResponse | undefined> => {
      if (message.type === "BOSS_SEARCH_PROGRESS") {
        if (window.location.origin === "http://localhost:3000") {
          window.postMessage(message, window.location.origin);
        }
        return;
      }
      if (message.type === "CAPTURE_BOSS_VISIBLE") return captureBossVisible(message);
      if (message.type !== "ACTION" && message.type !== "REQUEST_USER_ACTION") return;
      const result: ActionResultMessage = await executeAction(message);
      await browser.runtime.sendMessage(result);
      return result;
    });
  },
});

function isBossBridgeRequest(value: unknown): value is BossBridgeRequest {
  if (!value || typeof value !== "object") return false;
  const message = value as Partial<BossBridgeRequest>;
  return message.source === "careerpilot-web" && [
    "BOSS_EXTENSION_PING",
    "BOSS_SEARCH_REQUEST",
    "BOSS_SEARCH_RESUME_REQUEST",
    "BOSS_SEARCH_STATUS_REQUEST",
    "BOSS_TASK_LAUNCH_REQUEST",
    "BOSS_TASK_BATCH_LAUNCH_REQUEST",
  ].includes(message.type ?? "");
}

async function forwardBridgeRequest(message: BossBridgeRequest): Promise<void> {
  try {
    const response = await browser.runtime.sendMessage(message) as BossBridgeResponse;
    window.postMessage(response, window.location.origin);
  } catch (error) {
    const common = {
      source: "careerpilot-extension" as const,
      request_id: message.request_id,
      success: false,
      error: error instanceof Error ? error.message : "CareerPilot Extension 请求失败",
    };
    let response: BossBridgeResponse;
    if (message.type === "BOSS_TASK_LAUNCH_REQUEST") {
      response = { ...common, type: "BOSS_TASK_LAUNCH_RESULT", task_id: message.task_id };
    } else if (message.type === "BOSS_TASK_BATCH_LAUNCH_REQUEST") {
      response = { ...common, type: "BOSS_TASK_BATCH_LAUNCH_RESULT", accepted_count: 0 };
    } else if (message.type === "BOSS_SEARCH_STATUS_REQUEST") {
      response = { source: "careerpilot-extension", type: "BOSS_SEARCH_STATUS_RESULT", request_id: message.request_id, task: null };
    } else {
      response = { ...common, type: "BOSS_SEARCH_RESULT", page_url: "", jobs: [], page_state: "UNKNOWN_STATE" };
    }
    window.postMessage(response, window.location.origin);
  }
}

async function captureBossVisible(request: BossCaptureRequest): Promise<BossCaptureResponse> {
  if (!isBossPageUrl()) {
    return { type: "BOSS_CAPTURE_RESULT", success: false, page_url: window.location.href, jobs: [], page_state: "UNKNOWN_STATE", error: "当前页面不是 BOSS 直聘域名" };
  }
  const pageState = detectBossPageState();
  if (pageState !== "READY") {
    const diagnostics = describeBossJobSurface();
    const error = pageState === "UNKNOWN_STATE"
      ? `BOSS 搜索结果仍在加载，或当前页面不是职位结果页。${diagnostics}`
      : `BOSS 页面状态为 ${pageState}，需要人工处理。${diagnostics}`;
    return { type: "BOSS_CAPTURE_RESULT", success: false, page_url: window.location.href, jobs: [], page_state: pageState, error };
  }
  const jobs = request.include_details === false
    ? extractVisibleBossJobs().slice(0, request.max_jobs ?? 20)
    : await extractVisibleBossJobsWithDetails(
      request.max_jobs ?? 20,
      async (job, collectedCount, targetCount) => {
        if (!request.request_id) return;
        const progress: BossCaptureProgress = {
          type: "BOSS_CAPTURE_PROGRESS",
          request_id: request.request_id,
          page_url: window.location.href,
          jobs: [job],
          collected_count: collectedCount,
          target_count: targetCount,
          page_state: detectBossPageState(),
        };
        await browser.runtime.sendMessage(progress);
      },
    );
  const finalPageState = detectBossPageState();
  if (finalPageState !== "READY") {
    return { type: "BOSS_CAPTURE_RESULT", success: false, page_url: window.location.href, jobs, page_state: finalPageState, error: `采集过程中 BOSS 页面状态变为 ${finalPageState}，需要人工处理。${describeBossJobSurface()}` };
  }
  if (jobs.length === 0) {
    const diagnostics = describeBossJobSurface();
    const error = diagnostics.includes("empty=true")
      ? `BOSS 当前搜索没有返回匹配职位。${diagnostics}`
      : `BOSS 页面尚未产生可解析的职位卡片。${diagnostics}`;
    return { type: "BOSS_CAPTURE_RESULT", success: false, page_url: window.location.href, jobs, page_state: finalPageState, error };
  }
  return { type: "BOSS_CAPTURE_RESULT", success: true, page_url: window.location.href, jobs, page_state: finalPageState };
}

async function executeAction(message: ActionMessage): Promise<ActionResultMessage> {
  const action = message.action;
  try {
    if (action.action === "CLICK") {
      if (isBossPageUrl() && detectBossPageState() !== "READY") {
        return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { text: document.body.innerText.slice(0, 1000), page_url: window.location.href, platform: "boss" }, page_state: detectBossPageState() };
      }
      if (isBossPageUrl() && action.metadata?.mode === "boss_immediate_communication") {
        return executeBossImmediateCommunication(action);
      }
      const element = findSemanticElement(action);
      if (!(element instanceof HTMLElement)) throw new Error("Semantic target not found");
      element.click();
    } else if (action.action === "TYPE") {
      const element = findSemanticElement(action);
      if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) throw new Error("Type target not found");
      element.value = action.value ?? "";
      element.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (action.action === "SCROLL") {
      window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
    } else if (action.action === "WAIT") {
      await new Promise((resolve) => window.setTimeout(resolve, action.wait_ms ?? 300));
    } else if (action.action === "REQUEST_USER_ACTION") {
      return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { acknowledged: true }, page_state: document.title };
    } else if (action.action === "CHECK_STATE" && isBossPageUrl()) {
      return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { text: document.body.innerText.slice(0, 1000), page_url: window.location.href, platform: "boss" }, page_state: detectBossPageState() };
    } else if (action.action === "EXTRACT" && isBossPageUrl() && action.metadata?.mode === "boss_visible_jobs") {
      return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { platform: "boss", page_url: window.location.href, jobs: extractVisibleBossJobs(), collection_mode: "visible_page_only" }, page_state: detectBossPageState() };
    }
    return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { text: document.body.innerText.slice(0, 1000) }, page_state: document.title };
  } catch (error) {
    return { type: "ACTION_RESULT", action_id: action.id, success: false, error: error instanceof Error ? error.message : "Action failed", page_state: document.title };
  }
}

function executeBossImmediateCommunication(action: ActionMessage["action"]): ActionResultMessage {
  const candidates = findVisibleInteractiveElements(action.target?.selector);
  const immediateButton = candidates.find((element) => normalizedText(element) === "立即沟通");
  if (immediateButton) {
    immediateButton.scrollIntoView({ block: "center", behavior: "instant" });
    immediateButton.click();
    return {
      type: "ACTION_RESULT",
      action_id: action.id,
      success: true,
      data: {
        boss_action: "immediate_communication",
        communication_status: "started",
        clicked_text: "立即沟通",
        page_url: window.location.href,
        platform: "boss",
        text: document.body.innerText.slice(0, 1500),
      },
      page_state: detectBossPageState(),
    };
  }

  const alreadyContacted = candidates.find((element) => normalizedText(element) === "继续沟通");
  if (alreadyContacted) {
    return {
      type: "ACTION_RESULT",
      action_id: action.id,
      success: true,
      data: {
        boss_action: "immediate_communication",
        communication_status: "already_contacted",
        clicked_text: "继续沟通",
        page_url: window.location.href,
        platform: "boss",
        text: document.body.innerText.slice(0, 1500),
      },
      page_state: detectBossPageState(),
    };
  }

  return {
    type: "ACTION_RESULT",
    action_id: action.id,
    success: false,
    data: {
      boss_action: "immediate_communication",
      communication_status: "button_not_found",
      page_url: window.location.href,
      platform: "boss",
      text: document.body.innerText.slice(0, 1500),
    },
    page_state: detectBossPageState(),
    error: "未在当前 BOSS 职位详情中找到可见且可点击的“立即沟通”按钮",
  };
}

function findVisibleInteractiveElements(selector?: string | null): HTMLElement[] {
  const elements: HTMLElement[] = [];
  if (selector) {
    try {
      elements.push(...document.querySelectorAll<HTMLElement>(selector));
    } catch {
      // Continue with semantic fallbacks if a platform selector becomes invalid.
    }
  }
  elements.push(...document.querySelectorAll<HTMLElement>("button, a, [role='button']"));
  return [...new Set(elements)].filter((element) => {
    const disabled = element.matches(":disabled") || element.getAttribute("aria-disabled") === "true";
    return !disabled && element.getClientRects().length > 0;
  });
}

function normalizedText(element: HTMLElement): string {
  return (element.innerText || element.textContent || "").replace(/\s+/g, "").trim();
}
