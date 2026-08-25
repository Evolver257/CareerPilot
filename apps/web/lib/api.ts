export type Job = {
  id: string;
  platform: string;
  external_job_id: string | null;
  company_id: string | null;
  title: string;
  description: string;
  location: string | null;
  salary_min: number | null;
  salary_max: number | null;
  job_type: string | null;
  education_requirement: string | null;
  experience_requirement: string | null;
  publish_time: string | null;
  source_url: string | null;
  raw_data: Record<string, unknown>;
  normalized_data: Record<string, unknown>;
  content_hash: string | null;
  created_at: string;
  updated_at: string;
};

export type JobListResponse = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
};

export type JobSalary = {
  minimum: number | null;
  maximum: number | null;
  currency: string;
};

export type JobRequirements = {
  education: string;
  experience: string;
  responsibilities: string[];
};

export type StructuredJob = {
  title: string;
  role_category: string;
  level: string;
  job_type: string;
  location: string;
  salary: JobSalary;
  required_skills: string[];
  preferred_skills: string[];
  education_requirement: string;
  experience_requirement: string;
  responsibilities: string[];
  keywords: string[];
  summary: string;
};

export type JobSkill = {
  id: string;
  job_id: string;
  skill_name: string;
  skill_type: "required" | "preferred" | "optional";
  importance: number;
  confidence: number;
  created_at: string;
};

export type JobAnalysis = {
  job: Job;
  structured_job: StructuredJob;
  requirements: JobRequirements;
  skills: JobSkill[];
};

export type JobImportResponse = {
  items: JobAnalysis[];
  created: number;
  duplicates: number;
  total: number;
};

export type ResumeEvidence = {
  chunk_id: string;
  chunk_type: string;
  content: string;
  metadata: Record<string, unknown>;
  semantic_score: number;
  rerank_score: number;
};

export type JobScore = {
  id: string;
  job_id: string;
  resume_id: string;
  semantic_score: number;
  skill_score: number;
  education_score: number;
  experience_score: number;
  location_score: number;
  preference_score: number;
  llm_score: number;
  final_score: number;
  rules_passed: boolean;
  rule_reasons: string[];
  matched_skills: string[];
  missing_skills: string[];
  strengths: string[];
  gaps: string[];
  risks: string[];
  resume_evidence: ResumeEvidence[];
  recommendation: "strong_apply" | "apply" | "maybe" | "skip";
  reasoning_summary: string;
  score_version: string;
  weights: Record<string, number>;
  created_at: string;
};

export type RankingStageName =
  | "rule_filter"
  | "embedding_rank"
  | "reranker"
  | "llm_judge"
  | "final_ranking";

export type RankingTraceCandidate = {
  job_id: string;
  title: string;
  rank: number | null;
  score: number | null;
  selected: boolean;
  passed: boolean | null;
  reasons: string[];
  sub_scores: Record<string, number>;
  recommendation: JobScore["recommendation"] | null;
};

export type RankingTraceStage = {
  name: RankingStageName;
  input_count: number;
  output_count: number;
  duration_ms: number;
  candidates: RankingTraceCandidate[];
};

export type JobRankingResponse = {
  items: Array<{ rank: number; job: Job; score: JobScore }>;
  total_candidates: number;
  trace: {
    run_id: string;
    version: string;
    started_at: string;
    completed_at: string;
    llm_calls: number;
    token_usage: LLMUsage;
    config: {
      candidate_limit: number;
      top_k_embedding: number;
      top_k_rerank: number;
      top_k_llm: number;
      final_top_k: number;
    };
    stages: RankingTraceStage[];
  };
};

export type CampaignStatus =
  | "DRAFT"
  | "RANKING"
  | "WAITING_APPROVAL"
  | "RUNNING"
  | "PAUSED"
  | "COMPLETED"
  | "CANCELLED"
  | "FAILED";

export type ApplicationStatus =
  | "DISCOVERED"
  | "ANALYZED"
  | "QUALIFIED"
  | "WAITING_APPROVAL"
  | "APPROVED"
  | "QUEUED"
  | "EXECUTING"
  | "SUBMITTED"
  | "PAUSED"
  | "CANCELLED"
  | "CAPTCHA_REQUIRED"
  | "LOGIN_REQUIRED"
  | "PLATFORM_LIMIT"
  | "DOM_CHANGED"
  | "RISK_CONTROL"
  | "UNKNOWN_STATE"
  | "FAILED";

export type Application = {
  id: string;
  user_id: string;
  campaign_id: string;
  job_id: string;
  resume_id: string;
  platform: string;
  status: ApplicationStatus;
  message: string;
  applied_at: string | null;
  failure_reason: string | null;
  metadata: {
    state_history?: Array<{ from: string | null; to: string; event: string; at: string }>;
    [key: string]: unknown;
  };
  created_at: string;
  updated_at: string;
};

export type Campaign = {
  id: string;
  user_id: string;
  resume_id: string | null;
  name: string;
  status: CampaignStatus;
  query: string;
  min_score: number;
  max_jobs: number;
  target_cities: string[];
  filters: Record<string, unknown>;
  candidate_count: number;
  waiting_approval_count: number;
  queued_count: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type CampaignJob = {
  id: string;
  campaign_id: string;
  job_id: string;
  rank: number;
  score: number;
  status: ApplicationStatus | "REJECTED";
  job: Job;
  application: Application | null;
  created_at: string;
  updated_at: string;
};

export type CampaignDetail = Campaign & { candidate_jobs: CampaignJob[] };

export type CampaignListResponse = { items: Campaign[]; total: number };

export type ApplicationListItem = Application & { job: Job; campaign_name: string };

export type ApplicationListResponse = { items: ApplicationListItem[]; total: number };

export type AgentRunStatus =
  | "PENDING"
  | "RUNNING"
  | "PAUSED"
  | "WAITING_FOR_USER"
  | "COMPLETED"
  | "CANCELLED"
  | "FAILED"
  | "TIMED_OUT";

export type AgentCandidate = {
  job_id: string;
  title: string;
  score: number;
  recommendation: JobScore["recommendation"];
  score_id: string | null;
};

export type AgentStep = {
  id: string;
  run_id: string;
  sequence: number;
  step_type: string;
  tool_name: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  status: "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  attempt: number;
  latency_ms: number;
  error: string | null;
  created_at: string;
};

export type AgentEvent = {
  id: string;
  run_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type AgentRun = {
  id: string;
  user_id: string;
  campaign_id: string | null;
  agent_type: string;
  status: AgentRunStatus;
  input: { goal?: string; resume_id?: string; [key: string]: unknown };
  output: {
    campaign_id?: string;
    candidates?: AgentCandidate[];
    prompt?: string;
    user_action_required?: boolean;
    approved?: boolean;
    queued_count?: number;
    [key: string]: unknown;
  };
  state: Record<string, unknown>;
  memory: Record<string, unknown>;
  max_steps: number;
  timeout_seconds: number;
  max_retries: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps: AgentStep[];
  events: AgentEvent[];
};

export type AgentRunListResponse = { items: AgentRun[]; total: number };

export type LLMUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
  source: string;
};

export type DashboardResponse = {
  summary: {
    jobs_total: number;
    high_match_jobs: number;
    campaigns_total: number;
    campaign_candidates: number;
    applications_total: number;
    submitted_applications: number;
    attention_required: number;
  };
  funnel: Array<{
    key: string;
    label: string;
    count: number;
    conversion_rate: number | null;
  }>;
  application_status: Array<{ status: string; count: number }>;
  agent: {
    total_runs: number;
    active_runs: number;
    completed_runs: number;
    failed_runs: number;
    total_steps: number;
    failed_steps: number;
    retry_count: number;
    average_latency_ms: number;
  };
  token_usage: LLMUsage;
  refreshed_at: string;
};

export type BrowserTaskStatus =
  | "PENDING"
  | "CONNECTING"
  | "RUNNING"
  | "WAITING_FOR_USER"
  | "COMPLETED"
  | "CANCELLED"
  | "FAILED";

export type BrowserAction = {
  id: string;
  action: string;
  target?: { strategy: string; name?: string | null; selector?: string | null } | null;
  value?: string | null;
  url?: string | null;
  metadata: Record<string, unknown>;
};

export type BrowserTaskEvent = {
  id: string;
  task_id: string;
  event_type: string;
  action_id: string | null;
  sequence: number | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type BrowserTask = {
  id: string;
  user_id: string;
  application_id: string;
  campaign_id: string | null;
  platform: string;
  task_type: string;
  scenario: string;
  status: BrowserTaskStatus;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  current_action: BrowserAction | Record<string, unknown>;
  failure_reason: string | null;
  action_sequence: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  events: BrowserTaskEvent[];
};

export type BrowserTaskListResponse = { items: BrowserTask[]; total: number };

export type PlatformAdapter = {
  name: string;
  label: string;
  mode: string;
  safe_for_automation: boolean;
};

export type ResumeEducation = {
  institution: string;
  degree: string;
  field: string;
  start_date: string | null;
  end_date: string | null;
  details: string[];
};

export type ResumeExperience = {
  company: string;
  role: string;
  start_date: string | null;
  end_date: string | null;
  location: string | null;
  bullets: string[];
};

export type ResumeProject = {
  name: string;
  description: string;
  technologies: string[];
  highlights: string[];
};

export type ResumeAward = {
  name: string;
  issuer: string | null;
  date: string | null;
  details: string;
};

export type ResumePublication = {
  title: string;
  venue: string | null;
  date: string | null;
  details: string;
};

export type ResumeProfile = {
  education: ResumeEducation[];
  skills: string[];
  projects: ResumeProject[];
  experience: ResumeExperience[];
  awards: ResumeAward[];
  publications: ResumePublication[];
  target_roles: string[];
  summary: string;
};

export type Resume = {
  id: string;
  user_id: string;
  name: string;
  original_filename: string | null;
  raw_text: string;
  structured_profile: ResumeProfile;
  version: number;
  is_default: boolean;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type ResumeListResponse = {
  items: Resume[];
  total: number;
};

export type ResumeChunk = {
  id: string;
  resume_id: string;
  chunk_type: string;
  content: string;
  metadata: Record<string, unknown>;
  embedding_dimensions: number;
  created_at: string;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `API request failed: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Keep the HTTP status when the API response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function getJobs(search?: string): Promise<JobListResponse> {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  return apiFetch<JobListResponse>(`/api/jobs${query}`);
}

export function getDashboard(): Promise<DashboardResponse> {
  return apiFetch<DashboardResponse>("/api/dashboard");
}

export function getJob(id: string): Promise<Job> {
  return apiFetch<Job>(`/api/jobs/${encodeURIComponent(id)}`);
}

export function analyzeJob(id: string): Promise<JobAnalysis> {
  return apiFetch<JobAnalysis>(`/api/jobs/${encodeURIComponent(id)}/analyze`, { method: "POST" });
}

export function scoreJob(id: string, resumeId?: string): Promise<JobScore> {
  return apiFetch<JobScore>(`/api/jobs/${encodeURIComponent(id)}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resumeId ? { resume_id: resumeId } : {}),
  });
}

export function rankJobs(resumeId?: string): Promise<JobRankingResponse> {
  return apiFetch<JobRankingResponse>("/api/jobs/rank", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resumeId ? { resume_id: resumeId } : {}),
  });
}

export function getCampaigns(): Promise<CampaignListResponse> {
  return apiFetch<CampaignListResponse>("/api/campaigns");
}

export function getCampaign(id: string): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/campaigns/${encodeURIComponent(id)}`);
}

export function createCampaign(payload: {
  name: string;
  resume_id?: string;
  query?: string;
  keywords?: string[];
  min_score: number;
  max_jobs: number;
  target_cities?: string[];
}): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>("/api/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function campaignAction(
  id: string,
  action: "start" | "pause" | "resume" | "cancel",
): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/campaigns/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
}

export function approveCampaignJobs(id: string, jobIds: string[]): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/campaigns/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: jobIds }),
  });
}

export function getApplications(): Promise<ApplicationListResponse> {
  return apiFetch<ApplicationListResponse>("/api/applications");
}

export function getAgentRuns(): Promise<AgentRunListResponse> {
  return apiFetch<AgentRunListResponse>("/api/agent-runs");
}

export function getAgentRun(id: string): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agent-runs/${encodeURIComponent(id)}`);
}

export function createAgentRun(payload: {
  goal: string;
  resume_id?: string;
  auto_start?: boolean;
  max_steps?: number;
  timeout_seconds?: number;
  max_retries?: number;
}): Promise<AgentRun> {
  return apiFetch<AgentRun>("/api/agent-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function agentRunAction(
  id: string,
  action: "start" | "pause" | "cancel" | "retry",
): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agent-runs/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
}

export function resumeAgentRun(
  id: string,
  payload: { approved?: boolean; selected_job_ids?: string[] } = {},
): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agent-runs/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getBrowserTasks(): Promise<BrowserTaskListResponse> {
  return apiFetch<BrowserTaskListResponse>("/api/browser-tasks");
}

export function getPlatformAdapters(): Promise<PlatformAdapter[]> {
  return apiFetch<PlatformAdapter[]>("/api/browser-tasks/platforms");
}

export function getBrowserTask(id: string): Promise<BrowserTask> {
  return apiFetch<BrowserTask>(`/api/browser-tasks/${encodeURIComponent(id)}`);
}

export function createBrowserTask(payload: {
  application_id: string;
  platform?: "mock" | "careerboard";
  scenario?: string;
  auto_start?: boolean;
}): Promise<BrowserTask> {
  return apiFetch<BrowserTask>("/api/browser-tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function browserTaskAction(
  id: string,
  action: "start" | "cancel",
): Promise<BrowserTask> {
  return apiFetch<BrowserTask>(`/api/browser-tasks/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
}

export function resumeBrowserTask(
  id: string,
  decision = "resolved",
  note?: string,
): Promise<BrowserTask> {
  return apiFetch<BrowserTask>(`/api/browser-tasks/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  });
}

export function simulateBrowserExtension(id: string): Promise<BrowserTask> {
  return apiFetch<BrowserTask>(`/api/browser-tasks/${encodeURIComponent(id)}/mock-extension`, {
    method: "POST",
  });
}

export function browserTaskWebSocketUrl(id: string): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  return `${base}/api/browser-tasks/ws/${encodeURIComponent(id)}`;
}

export function importJobs(payload: {
  mode: "single" | "mock";
  raw_jd?: string;
  platform?: string;
  external_job_id?: string;
  limit?: number;
}): Promise<JobImportResponse> {
  return apiFetch<JobImportResponse>("/api/jobs/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getResumes(): Promise<ResumeListResponse> {
  return apiFetch<ResumeListResponse>("/api/resumes");
}

export function getResume(id: string): Promise<Resume> {
  return apiFetch<Resume>(`/api/resumes/${encodeURIComponent(id)}`);
}

export function getResumeChunks(id: string): Promise<ResumeChunk[]> {
  return apiFetch<ResumeChunk[]>(`/api/resumes/${encodeURIComponent(id)}/chunks`);
}

export function uploadResume(file: File, name?: string): Promise<Resume> {
  const formData = new FormData();
  formData.append("file", file);
  if (name?.trim()) formData.append("name", name.trim());
  return apiFetch<Resume>("/api/resumes", { method: "POST", body: formData });
}

export function parseResume(id: string): Promise<Resume> {
  return apiFetch<Resume>(`/api/resumes/${encodeURIComponent(id)}/parse`, { method: "POST" });
}
