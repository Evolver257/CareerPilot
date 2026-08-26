export type BrowserAction = {
  id: string;
  action: "NAVIGATE" | "CLICK" | "TYPE" | "EXTRACT" | "SCROLL" | "WAIT" | "CHECK_STATE" | "SCREENSHOT" | "REQUEST_USER_ACTION";
  target?: { strategy: string; name?: string | null; selector?: string | null } | null;
  value?: string | null;
  url?: string | null;
  wait_ms?: number;
  metadata?: Record<string, unknown>;
};

export type ActionMessage = {
  type: "ACTION" | "REQUEST_USER_ACTION";
  task_id: string;
  sequence?: number;
  action: BrowserAction;
};

export type BrowserTaskLifecycleMessage = {
  type: "TASK_COMPLETED" | "TASK_FAILED" | "TASK_CANCELLED";
  task_id: string;
  status: "COMPLETED" | "FAILED" | "CANCELLED";
  error?: string;
};

export type ActionResultMessage = {
  type: "ACTION_RESULT";
  action_id: string;
  success: boolean;
  data?: Record<string, unknown>;
  page_state?: string;
  error?: string;
};

export type BossCaptureRequest = {
  type: "CAPTURE_BOSS_VISIBLE";
  max_jobs?: number;
  include_details?: boolean;
};

export type BossCaptureResponse = {
  type: "BOSS_CAPTURE_RESULT";
  success: boolean;
  page_url: string;
  jobs: import("./platforms/boss").BossVisibleJob[];
  page_state: import("./platforms/boss").BossPageState;
  error?: string;
};

export type BossExtensionPing = {
  source: "careerpilot-web";
  type: "BOSS_EXTENSION_PING";
  request_id: string;
};

export type BossExtensionPong = {
  source: "careerpilot-extension";
  type: "BOSS_EXTENSION_PONG";
  request_id: string;
  version: string;
};

export type BossSearchRequest = {
  source: "careerpilot-web";
  type: "BOSS_SEARCH_REQUEST";
  request_id: string;
  payload: {
    requirements: string;
    city: string;
    max_jobs: number;
  };
};

export type BossSearchResponse = {
  source: "careerpilot-extension";
  type: "BOSS_SEARCH_RESULT";
  request_id: string;
  success: boolean;
  page_url: string;
  jobs: import("./platforms/boss").BossVisibleJob[];
  page_state: import("./platforms/boss").BossPageState;
  error?: string;
};

export type BossTaskLaunchRequest = {
  source: "careerpilot-web";
  type: "BOSS_TASK_LAUNCH_REQUEST";
  request_id: string;
  task_id: string;
  url: string;
};

export type BossTaskLaunchResponse = {
  source: "careerpilot-extension";
  type: "BOSS_TASK_LAUNCH_RESULT";
  request_id: string;
  task_id: string;
  success: boolean;
  error?: string;
};

export type BossTaskBatchLaunchRequest = {
  source: "careerpilot-web";
  type: "BOSS_TASK_BATCH_LAUNCH_REQUEST";
  request_id: string;
  tasks: Array<{ task_id: string; url: string }>;
};

export type BossTaskBatchLaunchResponse = {
  source: "careerpilot-extension";
  type: "BOSS_TASK_BATCH_LAUNCH_RESULT";
  request_id: string;
  success: boolean;
  accepted_count: number;
  error?: string;
};

export type BossBridgeRequest = BossExtensionPing | BossSearchRequest | BossTaskLaunchRequest | BossTaskBatchLaunchRequest;
export type BossBridgeResponse = BossExtensionPong | BossSearchResponse | BossTaskLaunchResponse | BossTaskBatchLaunchResponse;

export function findSemanticElement(action: BrowserAction): Element | null {
  if (action.target?.selector) {
    const selected = document.querySelector(action.target.selector);
    if (selected) return selected;
  }
  const name = action.target?.name?.trim().toLocaleLowerCase();
  if (!name) return null;
  return [...document.querySelectorAll("button, a, input, textarea, [role='button']")].find((element) => {
    const text = (element.textContent || (element as HTMLInputElement).value || "").trim().toLocaleLowerCase();
    return text.includes(name);
  }) ?? null;
}
