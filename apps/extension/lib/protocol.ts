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

export type BrowserTaskBatchLifecycleMessage = {
  type: "TASK_BATCH_CANCELLED";
  task_ids: string[];
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
  request_id?: string;
  max_jobs?: number;
  include_details?: boolean;
  require_search_page?: boolean;
};

export type BossCaptureCancelRequest = {
  type: "CANCEL_BOSS_CAPTURE";
  request_id: string;
};

export type BossCaptureProgress = {
  type: "BOSS_CAPTURE_PROGRESS";
  request_id: string;
  page_url: string;
  jobs: import("./platforms/boss").BossVisibleJob[];
  collected_count: number;
  target_count: number;
  page_state: import("./platforms/boss").BossPageState;
};

export type BossCaptureResponse = {
  type: "BOSS_CAPTURE_RESULT";
  success: boolean;
  page_url: string;
  jobs: import("./platforms/boss").BossVisibleJob[];
  page_state: import("./platforms/boss").BossPageState;
  cancelled?: boolean;
  error?: string;
};

export type ZhaopinCaptureRequest = {
  source: "careerpilot-web";
  type: "ZHAOPIN_CAPTURE_REQUEST";
  request_id: string;
  max_jobs?: number;
};

export type ZhaopinCaptureTabRequest = {
  type: "CAPTURE_ZHAOPIN_VISIBLE";
  request_id: string;
  max_jobs?: number;
};

export type ZhaopinCaptureResponse = {
  empty?: boolean;
  source?: "careerpilot-extension";
  type: "ZHAOPIN_CAPTURE_RESULT";
  request_id?: string;
  success: boolean;
  page_url: string;
  jobs: import("./platforms/zhaopin").ZhaopinVisibleJob[];
  page_state: import("./platforms/zhaopin").ZhaopinPageState;
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
    quick_score_threshold: number;
  };
};

export type BossSearchResumeRequest = {
  source: "careerpilot-web";
  type: "BOSS_SEARCH_RESUME_REQUEST";
  request_id: string;
};

export type BossSearchCancelRequest = {
  source: "careerpilot-web";
  type: "BOSS_SEARCH_CANCEL_REQUEST";
  request_id: string;
};

export type BossSearchCancelResponse = {
  source: "careerpilot-extension";
  type: "BOSS_SEARCH_CANCEL_RESULT";
  request_id: string;
  success: boolean;
  task: BossBackgroundSearchTask | null;
  error?: string;
};

export type BossSearchResponse = {
  source: "careerpilot-extension";
  type: "BOSS_SEARCH_RESULT";
  request_id: string;
  success: boolean;
  page_url: string;
  jobs: import("./platforms/boss").BossVisibleJob[];
  page_state: import("./platforms/boss").BossPageState;
  background_task?: BossBackgroundSearchTask;
  error?: string;
};

export type BossSearchProgress = {
  source: "careerpilot-extension";
  type: "BOSS_SEARCH_PROGRESS";
  request_id: string;
  page_url: string;
  jobs: import("./platforms/boss").BossVisibleJob[];
  collected_count: number;
  target_count: number;
  page_state: import("./platforms/boss").BossPageState;
  background_task?: BossBackgroundSearchTask;
};

export type BossPersistedJobSummary = {
  id: string;
  external_job_id: string | null;
  title: string;
  location: string | null;
  company_name: string | null;
  salary_text: string | null;
  description_source: "detail_panel" | "card_summary";
};

export type BossBackgroundSearchTask = {
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
  page_state: import("./platforms/boss").BossPageState;
  persisted_jobs: BossPersistedJobSummary[];
  error?: string;
  started_at: string;
  updated_at: string;
  finished_at?: string;
};

export type BossSearchStatusRequest = {
  source: "careerpilot-web";
  type: "BOSS_SEARCH_STATUS_REQUEST";
  request_id: string;
};

export type BossSearchStatusResponse = {
  source: "careerpilot-extension";
  type: "BOSS_SEARCH_STATUS_RESULT";
  request_id: string;
  task: BossBackgroundSearchTask | null;
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
  type: "BOSS_TASK_BATCH_LAUNCH_REQUEST" | "RECRUITMENT_TASK_BATCH_LAUNCH_REQUEST";
  request_id: string;
  tasks: Array<{ task_id: string; url: string; platform?: "boss" | "zhaopin" }>;
};

export type BossTaskBatchLaunchResponse = {
  source: "careerpilot-extension";
  type: "BOSS_TASK_BATCH_LAUNCH_RESULT" | "RECRUITMENT_TASK_BATCH_LAUNCH_RESULT";
  request_id: string;
  success: boolean;
  accepted_count: number;
  error?: string;
};

export type BossBridgeRequest = BossExtensionPing | BossSearchRequest | BossSearchResumeRequest | BossSearchCancelRequest | BossSearchStatusRequest | BossTaskLaunchRequest | BossTaskBatchLaunchRequest;
export type BossBridgeResponse = BossExtensionPong | BossSearchProgress | BossSearchResponse | BossSearchCancelResponse | BossSearchStatusResponse | BossTaskLaunchResponse | BossTaskBatchLaunchResponse;
export type RecruitmentBridgeRequest = BossBridgeRequest | ZhaopinCaptureRequest | import("./collection-types").ZhaopinCollectionRequest;
export type RecruitmentBridgeResponse = BossBridgeResponse | ZhaopinCaptureResponse | import("./collection-types").ZhaopinCollectionResponse;

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
