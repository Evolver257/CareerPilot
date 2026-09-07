import type { ZhaopinPageState, ZhaopinVisibleJob } from "./platforms/zhaopin";

export type CollectedJob = {
  id: string; external_job_id: string; title: string; location: string | null;
  company_name: string | null; salary_text: string | null; education: string | null;
  score?: number; score_status?: "SUFFICIENT" | "PARTIAL" | "INSUFFICIENT_DATA" | "FAILED";
  score_confidence?: number; score_error?: string;
};
export type ZhaopinCollectionTask = {
  request_id: string;
  status: "RUNNING" | "WAITING_FOR_USER" | "INTERRUPTED" | "COMPLETED" | "FAILED" | "CANCELLED";
  search_url: string; page_url: string; target_count: number;
  resume_id?: string; quick_score_threshold: number;
  jobs: CollectedJob[]; pending: ZhaopinVisibleJob[]; page_signature?: string;
  search_tab_id?: number; detail_tab_id?: number;
  page_state: ZhaopinPageState; active_url?: string;
  created_count: number; updated_count: number; end_reason?: string; error?: string;
  started_at: string; updated_at: string;
};
export type ZhaopinCollectionRequest = {
  source: "careerpilot-web";
  type: "ZHAOPIN_SEARCH_REQUEST" | "ZHAOPIN_SEARCH_STATUS_REQUEST" | "ZHAOPIN_SEARCH_CANCEL_REQUEST" | "ZHAOPIN_SEARCH_RESUME_REQUEST" | "ZHAOPIN_SEARCH_OPEN_REQUEST";
  request_id: string;
  payload?: { search_url: string; max_jobs: number; resume_id?: string; quick_score_threshold: number };
};
export type ZhaopinCollectionResponse = {
  source: "careerpilot-extension"; type: "ZHAOPIN_TASK_STATE";
  request_id: string; task: ZhaopinCollectionTask | null; error?: string;
};
