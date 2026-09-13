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
  platform_metadata?: Record<string, unknown>;
  normalized_data: Record<string, unknown>;
  content_hash: string | null;
  job_fingerprint?: string | null;
  last_collected_at: string;
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
  qualifications: string[];
  preferred_qualifications: string[];
  benefits: string[];
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
  benefits: string[];
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
  input_fingerprint: string | null;
  judge_source: "llm" | "fallback";
  weights: Record<string, number>;
  created_at: string;
};

export type QuickJobScore = {
  job_id: string;
  resume_id: string;
  score: number;
  rules_passed: boolean;
  rule_reasons: string[];
  matched_skills: string[];
  missing_skills: string[];
  recommendation: JobScore["recommendation"];
  reasoning_summary: string;
  direction_score: number;
  score_confidence: number;
  score_status: "SUFFICIENT" | "PARTIAL" | "INSUFFICIENT_DATA" | "FAILED";
  confidence_factors: Record<string, number>;
  hard_constraint_ledger: Array<{
    requirement_group_id: string;
    reason: string;
    penalty: number;
    cap: number | null;
    affected_requirements: string[];
    source_text: string;
  }>;
  hard_constraint_passed: boolean;
  component_scores: Record<string, number>;
  requirement_matches: Array<{
    requirement_type: string;
    requirement_value: string;
    status: string;
    score: number;
    evidence: Array<Record<string, unknown>>;
    match_method: string;
    confidence: number;
    deduction: number;
    hard_constraint: boolean;
  }>;
  cached: boolean;
};

export type QuickScoreBatchResponse = {
  items: QuickJobScore[];
};

export type RankingStageName =
  | "rule_filter"
  | "embedding_rank"
  | "reranker"
  | "llm_judge"
  | "deterministic_rank"
  | "final_ranking";

export type RankingScoringMode = "fast" | "llm";

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
    cache_hits: number;
    fallback_count: number;
    token_usage: LLMUsage;
    config: {
      candidate_limit: number;
      top_k_embedding: number;
      top_k_rerank: number;
      top_k_llm: number;
      final_top_k: number;
      scoring_mode: RankingScoringMode;
    };
    stages: RankingTraceStage[];
  };
};

export type RankingRun = {
  id: string;
  resume_id: string;
  campaign_id: string | null;
  timeout_seconds: number;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "TIMED_OUT";
  stage: string;
  progress: number;
  processed_candidates: number;
  total_candidates: number;
  cache_hits: number;
  llm_calls: number;
  fallback_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
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
  | "MANUAL_REQUIRED"
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
  scoring_mode: RankingScoringMode;
  target_cities: string[];
  filters: Record<string, unknown>;
  candidate_count: number;
  waiting_approval_count: number;
  queued_count: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  ranking_run: RankingRun | null;
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

export type CampaignDetail = Campaign & { candidate_jobs: CampaignJob[]; reused_existing?: boolean };

export type CampaignListResponse = { items: Campaign[]; total: number };

export type ApplicationListItem = Application & { job: Job; campaign_name: string };

export type ApplicationListResponse = { items: ApplicationListItem[]; total: number; status_counts?: Record<string, number>; page?: number; page_size?: number };

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

export type LLMProviderName = "openai" | "anthropic";
export type ActiveLLMProvider = "mock" | LLMProviderName;

export type LLMProviderCredential = {
  provider: LLMProviderName;
  model: string;
  base_url: string;
  api_key_hint: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type LLMSettings = {
  active_provider: ActiveLLMProvider;
  providers: LLMProviderCredential[];
};

export type LLMConnectionTestResult = {
  provider: LLMProviderName;
  model: string;
  latency_ms: number;
  message: string;
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

export type BrowserTaskCampaignResponse = {
  campaign_id: string;
  queued_count: number;
  created_count: number;
  reused_count: number;
  failed_count: number;
  items: BrowserTask[];
  failures: Array<{ application_id: string; reason: string }>;
};

export type BrowserTaskCampaignGroup = {
  campaign_id: string;
  campaign_name: string;
  campaign_status: string;
  status: BrowserTaskStatus | "PARTIAL";
  platforms: string[];
  task_count: number;
  submitted_count: number;
  manual_count: number;
  active_count: number;
  waiting_count: number;
  failed_count: number;
  cancelled_count: number;
  created_at: string;
  updated_at: string;
  items: Array<{
    task: BrowserTask;
    job_id: string;
    job_title: string;
    application_status: ApplicationStatus;
  }>;
};

export type BrowserTaskCampaignGroupListResponse = {
  items: BrowserTaskCampaignGroup[];
  total: number;
};

export type PlatformAdapter = {
  name: string;
  label: string;
  mode: string;
  safe_for_automation: boolean;
};

export type BossVisibleJobCapture = {
  external_job_id: string;
  title: string;
  description: string;
  job_url: string;
  location: string | null;
  company_name: string | null;
  salary_text: string | null;
  tags: string[];
  description_source: "detail_panel" | "card_summary";
};

export type BossVisibleImportResponse = {
  platform: "boss";
  collection_mode: "visible_page_only";
  page_url: string;
  items: Job[];
  created: number;
  duplicates: number;
  updated: number;
  total: number;
  safety_notice: string;
};

export type RecruitmentPlatform = {
  id: string;
  name: string;
  enabled: boolean;
  capabilities: Record<string, boolean>;
  browser_session_required: boolean;
};

export type ZhaopinVisibleJobCapture = {
  external_job_id: string;
  title: string;
  description: string;
  job_url: string;
  location: string | null;
  company_name: string | null;
  salary_text: string | null;
  experience: string | null;
  education: string | null;
  requirements: string[];
  skills: string[];
  benefits: string[];
  raw_data: Record<string, unknown>;
};

export type RecruitmentImportResponse = {
  platform: string;
  collection_mode: string;
  page_url: string;
  items: Job[];
  created: number;
  duplicates: number;
  updated: number;
  total: number;
  safety_notice: string;
};

export type RecruitmentProviderHealth = {
  platform: string;
  status: string;
  result_count: number;
  cards_found: number;
  cards_parsed: number;
  parse_failure_count: number;
  error_code: string | null;
  message: string | null;
  duration_ms: number | null;
};

export type RecruitmentSearchResponse = {
  items: Job[];
  total: number;
  possible_duplicate_count: number;
  platform_status: Record<string, RecruitmentProviderHealth>;
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

export type MarketInsightStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export type MarketInsightMode = "fast" | "llm";

export type InsightDistribution = { label: string; count: number; percentage: number };
export type InsightSalaryBand = {
  unit: string;
  unit_label: string;
  sample_count: number;
  minimum: number;
  p25: number;
  median: number;
  p75: number;
  maximum: number;
};
export type InsightSkill = {
  name: string;
  count: number;
  percentage: number;
  required_count: number;
  preferred_count: number;
  category: "core" | "high_frequency" | "bonus" | "emerging";
  job_ids: string[];
};
export type InsightResponsibilityTheme = {
  name: string;
  count: number;
  percentage: number;
  examples: string[];
  job_ids: string[];
};
export type InsightRoleCluster = {
  name: string;
  count: number;
  percentage: number;
  titles: string[];
};
export type InsightLearningPhase = {
  weeks: string;
  title: string;
  objectives: string[];
  skills: string[];
  deliverables: string[];
  success_criteria: string[];
};
export type InsightEvidenceJob = {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  salary_text: string | null;
  education: string | null;
  experience: string | null;
  source_url: string | null;
  relevance: number;
};
export type MarketInsightResult = {
  query: string;
  generated_at: string;
  data_as_of: string | null;
  sample_count: number;
  confidence: string;
  warnings: string[];
  salary_bands: InsightSalaryBand[];
  education_distribution: InsightDistribution[];
  experience_distribution: InsightDistribution[];
  skills: InsightSkill[];
  responsibility_themes: InsightResponsibilityTheme[];
  role_clusters: InsightRoleCluster[];
  learning_roadmap: InsightLearningPhase[];
  summary_markdown: string;
  source_jobs: InsightEvidenceJob[];
  llm_source: string;
};
export type MarketInsight = {
  id: string;
  user_id: string;
  query: string;
  mode: MarketInsightMode;
  status: MarketInsightStatus;
  stage: string;
  progress: number;
  sample_count: number;
  confidence: string;
  fingerprint: string;
  request: Record<string, unknown>;
  report: MarketInsightResult | null;
  source_job_ids: string[];
  llm_source: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  cached: boolean;
};
export type MarketInsightListResponse = { items: MarketInsight[]; total: number };

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8010";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
    });
  } catch {
    throw new Error("无法连接 API 服务，请确认后端已启动并稍后重试。");
  }
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
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getJobs(options?: {
  search?: string;
  company?: string;
  location?: string;
  platform?: string;
  education?: string;
  experience?: string;
  salary_floor?: number;
  salary_ceiling?: number;
  page?: number;
  page_size?: number;
}): Promise<JobListResponse> {
  const query = new URLSearchParams();
  if (options?.search) query.set("search", options.search);
  if (options?.company) query.set("company", options.company);
  if (options?.location) query.set("location", options.location);
  if (options?.platform) query.set("platform", options.platform);
  if (options?.education) query.set("education", options.education);
  if (options?.experience) query.set("experience", options.experience);
  if (options?.salary_floor !== undefined) query.set("salary_floor", String(options.salary_floor));
  if (options?.salary_ceiling !== undefined) query.set("salary_ceiling", String(options.salary_ceiling));
  if (options?.page) query.set("page", String(options.page));
  if (options?.page_size) query.set("page_size", String(options.page_size));
  const suffix = query.size ? `?${query.toString()}` : "";
  return apiFetch<JobListResponse>(`/api/jobs${suffix}`);
}

export function getDashboard(): Promise<DashboardResponse> {
  return apiFetch<DashboardResponse>("/api/dashboard");
}

export function getLLMSettings(): Promise<LLMSettings> {
  return apiFetch<LLMSettings>("/api/llm/settings");
}

export function testLLMConnection(payload: {
  provider: LLMProviderName;
  api_key: string;
  model?: string;
  base_url?: string;
}): Promise<LLMConnectionTestResult> {
  return apiFetch<LLMConnectionTestResult>("/api/llm/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function testSavedLLMProvider(provider: LLMProviderName): Promise<LLMConnectionTestResult> {
  return apiFetch<LLMConnectionTestResult>(`/api/llm/providers/${provider}/test`, {
    method: "POST",
  });
}

export function saveLLMProvider(
  provider: LLMProviderName,
  payload: { api_key: string; model?: string; base_url?: string },
): Promise<LLMSettings> {
  return apiFetch<LLMSettings>(`/api/llm/providers/${provider}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function setActiveLLMProvider(provider: ActiveLLMProvider): Promise<LLMSettings> {
  return apiFetch<LLMSettings>("/api/llm/active", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
}

export function deleteLLMProvider(provider: LLMProviderName): Promise<void> {
  return apiFetch<void>(`/api/llm/providers/${provider}`, { method: "DELETE" });
}

export function getJob(id: string): Promise<Job> {
  return apiFetch<Job>(`/api/jobs/${encodeURIComponent(id)}`);
}

export function updateJob(id: string, payload: Partial<Pick<Job,
  "title" | "description" | "location" | "salary_min" | "salary_max" |
  "job_type" | "education_requirement" | "experience_requirement" | "source_url"
>>): Promise<Job> {
  return apiFetch<Job>(`/api/jobs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteJob(id: string): Promise<void> {
  return apiFetch<void>(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function analyzeJob(id: string): Promise<JobAnalysis> {
  return apiFetch<JobAnalysis>(`/api/jobs/${encodeURIComponent(id)}/analyze`, { method: "POST" });
}

export function scoreJob(id: string, resumeId?: string, force = false): Promise<JobScore> {
  return apiFetch<JobScore>(`/api/jobs/${encodeURIComponent(id)}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(resumeId ? { resume_id: resumeId } : {}), force }),
  });
}

export function quickScoreJobs(payload: {
  job_ids: string[];
  resume_id?: string;
}): Promise<QuickScoreBatchResponse> {
  return apiFetch<QuickScoreBatchResponse>("/api/jobs/quick-score", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function rankJobs(resumeId?: string): Promise<JobRankingResponse> {
  return apiFetch<JobRankingResponse>("/api/jobs/rank", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resumeId ? { resume_id: resumeId } : {}),
  });
}

export function startJobRanking(
  resumeId?: string,
  options: { scoringMode?: RankingScoringMode; deepLimit?: number } = {},
): Promise<RankingRun> {
  const scoringMode = options.scoringMode ?? "llm";
  const scoringLimit = scoringMode === "fast" ? 50 : (options.deepLimit ?? 10);
  return apiFetch<RankingRun>("/api/jobs/rank-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(resumeId ? { resume_id: resumeId } : {}),
      scoring_mode: scoringMode,
      top_k_rerank: scoringLimit,
      top_k_llm: scoringLimit,
    }),
  });
}

export function getJobRankingRun(id: string): Promise<RankingRun> {
  return apiFetch<RankingRun>(`/api/jobs/rank-runs/${encodeURIComponent(id)}`);
}

export function getJobRankingResult(id: string): Promise<JobRankingResponse> {
  return apiFetch<JobRankingResponse>(
    `/api/jobs/rank-runs/${encodeURIComponent(id)}/result`,
  );
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
  scoring_mode: RankingScoringMode;
  target_cities?: string[];
}): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>("/api/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateCampaign(id: string, payload: {
  name?: string;
  resume_id?: string;
  query?: string;
  keywords?: string[];
  min_score?: number;
  max_jobs?: number;
  scoring_mode?: RankingScoringMode;
  target_cities?: string[];
}): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/campaigns/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteCampaign(id: string): Promise<void> {
  return apiFetch<void>(`/api/campaigns/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function createCuratedCampaign(payload: {
  name: string;
  resume_id?: string;
  job_ids: string[];
  query?: string;
  message?: string;
}): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>("/api/campaigns/curated", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function campaignAction(
  id: string,
  action: "start" | "retry" | "pause" | "resume" | "cancel",
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

export function rejectCampaignJobs(id: string, jobIds: string[]): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/campaigns/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: jobIds }),
  });
}

export function getApplications(filters: { page?: number; page_size?: number; statuses?: string[]; campaign_id?: string; platform?: string } = {}): Promise<ApplicationListResponse> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (Array.isArray(value)) value.forEach((item) => query.append(key, item));
    else if (value !== undefined && value !== "") query.set(key, String(value));
  }
  return apiFetch<ApplicationListResponse>(`/api/applications?${query}`);
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

export function updateAgentRun(id: string, payload: {
  goal?: string;
  max_steps?: number;
  timeout_seconds?: number;
  max_retries?: number;
}): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agent-runs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteAgentRun(id: string): Promise<void> {
  return apiFetch<void>(`/api/agent-runs/${encodeURIComponent(id)}`, { method: "DELETE" });
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

export function getBrowserTaskCampaigns(): Promise<BrowserTaskCampaignGroupListResponse> {
  return apiFetch<BrowserTaskCampaignGroupListResponse>("/api/browser-tasks/campaigns");
}

export function cancelBrowserTaskCampaign(id: string): Promise<BrowserTaskCampaignGroup> {
  return apiFetch<BrowserTaskCampaignGroup>(`/api/browser-tasks/campaigns/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

export function deleteBrowserTaskCampaign(id: string): Promise<void> {
  return apiFetch<void>(`/api/browser-tasks/campaigns/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function getPlatformAdapters(): Promise<PlatformAdapter[]> {
  return apiFetch<PlatformAdapter[]>("/api/browser-tasks/platforms");
}

export function getBrowserTask(id: string): Promise<BrowserTask> {
  return apiFetch<BrowserTask>(`/api/browser-tasks/${encodeURIComponent(id)}`);
}

export function createBrowserTask(payload: {
  application_id: string;
  platform?: "mock" | "careerboard" | "boss" | "zhaopin";
  scenario?: string;
  auto_start?: boolean;
}): Promise<BrowserTask> {
  return apiFetch<BrowserTask>("/api/browser-tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createCampaignBrowserTasks(payload: {
  campaign_id: string;
  platform?: "mock" | "careerboard" | "boss" | "zhaopin";
  scenario?: string;
  auto_start?: boolean;
}): Promise<BrowserTaskCampaignResponse> {
  return apiFetch<BrowserTaskCampaignResponse>("/api/browser-tasks/campaign", {
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

export function importBossVisibleJobs(payload: {
  page_url: string;
  jobs: BossVisibleJobCapture[];
}): Promise<BossVisibleImportResponse> {
  return apiFetch<BossVisibleImportResponse>("/api/platforms/boss/import-visible", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getRecruitmentPlatforms(): Promise<RecruitmentPlatform[]> {
  return apiFetch<RecruitmentPlatform[]>('/api/platforms');
}

export function importZhaopinVisibleJobs(payload: {
  page_url: string;
  jobs: ZhaopinVisibleJobCapture[];
}): Promise<RecruitmentImportResponse> {
  return apiFetch<RecruitmentImportResponse>('/api/platforms/zhaopin/import-visible', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function searchRecruitmentPlatforms(payload: {
  keyword?: string;
  city?: string;
  page?: number;
  page_size?: number;
  platforms?: string[];
}): Promise<RecruitmentSearchResponse> {
  return apiFetch<RecruitmentSearchResponse>('/api/platforms/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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

export function updateResume(id: string, payload: {
  name?: string;
  raw_text?: string;
  is_default?: boolean;
}): Promise<Resume> {
  return apiFetch<Resume>(`/api/resumes/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteResume(id: string): Promise<void> {
  return apiFetch<void>(`/api/resumes/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function getMarketInsights(): Promise<MarketInsightListResponse> {
  return apiFetch<MarketInsightListResponse>("/api/market-insights");
}

export function getMarketInsight(id: string): Promise<MarketInsight> {
  return apiFetch<MarketInsight>(`/api/market-insights/${encodeURIComponent(id)}`);
}

export function createMarketInsight(payload: {
  query: string;
  mode: MarketInsightMode;
  cities?: string[];
  job_types?: string[];
  max_jobs?: number;
  force?: boolean;
}): Promise<MarketInsight> {
  return apiFetch<MarketInsight>("/api/market-insights", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function marketInsightAction(
  id: string,
  action: "cancel" | "retry",
): Promise<MarketInsight> {
  return apiFetch<MarketInsight>(`/api/market-insights/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
}

export function deleteMarketInsight(id: string): Promise<void> {
  return apiFetch<void>(`/api/market-insights/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export type CareerAdvisorIntent =
  | "market_research"
  | "learning_roadmap"
  | "resume_gap"
  | "role_comparison"
  | "job_recommendation"
  | "salary_analysis"
  | "skill_analysis"
  | "follow_up"
  | "general_career_chat";

export type JobKnowledgeFilters = {
  cities: string[];
  education: string | null;
  experience: string | null;
  job_types: string[];
  platform: string | null;
  salary_floor: number | null;
  salary_ceiling: number | null;
  published_after: string | null;
  published_before: string | null;
  collected_after?: string | null;
};

export type CareerAdvisorCitation = {
  id: string;
  message_id: string;
  job_id: string | null;
  chunk_id: string | null;
  citation_index: number;
  evidence: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type CareerAdvisorMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant" | string;
  content: string;
  status: string;
  intent: CareerAdvisorIntent | null;
  model_provider: string | null;
  model_name: string | null;
  token_usage: Record<string, unknown>;
  tool_trace: Array<Record<string, unknown>>;
  answer_metadata: Record<string, unknown>;
  latency_ms: number;
  error_message: string | null;
  ui_action?: CareerAdvisorUiAction | null;
  created_at: string;
  updated_at: string;
  citations: CareerAdvisorCitation[];
};

export type CareerAdvisorJobCandidate = {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  platform: string;
  result_source?: "knowledge_base" | "automated_collection";
  salary_text: string;
  education?: string | null;
  experience?: string | null;
  source_url?: string | null;
  last_collected_at?: string;
  match_score: number | null;
  match_reason?: string | null;
  warnings?: string[];
  is_fresh?: boolean;
  is_duplicate?: boolean;
  default_selected?: boolean;
};

export type CareerAdvisorUiAction = {
  type: "job_search_results" | "job_collection_request" | "application_confirmation" | "application_progress" | string;
  action_id: string;
  message_id?: string;
  campaign_id?: string;
  title?: string;
  summary?: string;
  plan_name?: string;
  resume_id?: string;
  resume_name?: string;
  job_ids?: string[];
  jobs?: CareerAdvisorJobCandidate[];
  items?: Array<Record<string, unknown>>;
  default_selected_job_ids?: string[];
  low_match_job_ids?: string[];
  expired_job_ids?: string[];
  warnings?: string[];
  confirmation_token?: string;
  status?: string;
  total_count?: number;
  submitted_count?: number;
  manual_count?: number;
  waiting_count?: number;
  result_source?: "knowledge_base" | "automated_collection";
  platform?: "boss" | "zhaopin" | "auto" | string;
  query?: string;
  city?: string;
  max_jobs?: number;
  quick_score_threshold?: number;
  auto_start?: boolean;
  high_score_only?: boolean;
  [key: string]: unknown;
};

export type CareerAdvisorSession = {
  id: string;
  user_id: string;
  resume_id: string | null;
  title: string;
  agent_type: string;
  context_filters: JobKnowledgeFilters;
  summary: string;
  created_at: string;
  updated_at: string;
  messages: CareerAdvisorMessage[];
  message_total: number;
  message_offset: number;
  message_has_more: boolean;
};

export type CareerAdvisorSessionJobsBindResponse = {
  session_id: string;
  linked_count: number;
  total_count: number;
  job_ids: string[];
};

export type CareerAdvisorSessionListResponse = {
  items: CareerAdvisorSession[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type CareerAdvisorCitationListResponse = {
  items: CareerAdvisorCitation[];
  total: number;
};

export type CareerAdvisorStreamEvent = {
  event_type: string;
  payload: Record<string, unknown>;
};

export type AgentMemoryType =
  | "USER_PROFILE"
  | "CAREER_GOAL"
  | "JOB_PREFERENCE"
  | "SKILL_BACKGROUND"
  | "LEARNING_PROGRESS"
  | "CONVERSATION_SUMMARY"
  | "USER_CONFIRMED_FACT";

export type AgentMemoryClass = "SEMANTIC" | "STATE" | "EPISODIC";
export type AgentMemoryStability = "STABLE" | "TEMPORARY" | "EVENT";
export type AgentMemoryStatus = "ACTIVE" | "SUPERSEDED" | "EXPIRED" | "DELETED";
export type AgentMemoryExtractionMethod = "USER" | "RULE" | "LLM" | "SUMMARY" | "SYSTEM_DERIVED";

export type AgentMemorySettings = {
  enabled: boolean;
  auto_save_non_sensitive: boolean;
  retention_days: number;
  allowed_types: AgentMemoryType[];
  allow_session_summaries: boolean;
  allow_unconfirmed_context: boolean;
  memory_token_budget: number;
  extraction_confidence_threshold: number;
};

export type AgentMemory = {
  id: string;
  memory_type: AgentMemoryType;
  memory_key: string;
  structured_value: Record<string, unknown>;
  scope: string | null;
  memory_class: AgentMemoryClass;
  stability: AgentMemoryStability;
  importance: number;
  status: AgentMemoryStatus;
  content: string;
  source_quote: string | null;
  extraction_method: AgentMemoryExtractionMethod;
  extraction_version: string;
  supersedes_id: string | null;
  last_verified_at: string | null;
  pinned: boolean;
  use_count: number;
  confidence: number;
  user_confirmed: boolean;
  sensitivity: string;
  provenance: Record<string, unknown>;
  valid_until: string | null;
  last_used_at: string | null;
  deleted_at: string | null;
  deleted_from_status: AgentMemoryStatus | null;
  created_at: string;
  updated_at: string;
};

export type AgentMemoryCandidate = {
  id: string;
  memory_type: AgentMemoryType;
  memory_key: string;
  structured_value: Record<string, unknown>;
  scope: string | null;
  memory_class: AgentMemoryClass;
  stability: AgentMemoryStability;
  importance: number;
  content: string;
  source_quote: string | null;
  extraction_method: AgentMemoryExtractionMethod;
  extraction_version: string;
  requires_confirmation: boolean;
  conflict_type: string | null;
  confidence: number;
  sensitivity: string;
  status: string;
  reason: string;
  created_at: string;
};

export type AgentMemoryEmbeddingRun = {
  id: string;
  mode: string;
  status: string;
  progress: number;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  current_memory_id: string | null;
  result_payload: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentMemoryEmbeddingHealth = {
  embedding_model: string;
  embedding_dimensions: number;
  provider_available: boolean;
  status: string;
  total: number;
  embedded: number;
  pending: number;
  failed: number;
  latest_run: AgentMemoryEmbeddingRun | null;
};

export function getAgentMemorySettings(): Promise<AgentMemorySettings> {
  return apiFetch<AgentMemorySettings>("/api/career-memory/settings");
}

export function updateAgentMemorySettings(
  payload: Partial<AgentMemorySettings>,
): Promise<AgentMemorySettings> {
  return apiFetch<AgentMemorySettings>("/api/career-memory/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getAgentMemories(options?: {
  query?: string;
  memoryType?: AgentMemoryType | "";
  includeDeleted?: boolean;
  status?: AgentMemoryStatus | "";
  extractionMethod?: AgentMemoryExtractionMethod | "";
  limit?: number;
  offset?: number;
}): Promise<{ items: AgentMemory[]; total: number; limit: number; offset: number; has_more: boolean }> {
  const params = new URLSearchParams();
  if (options?.query) params.set("query", options.query);
  if (options?.memoryType) params.set("memory_type", options.memoryType);
  if (options?.includeDeleted) params.set("include_deleted", "true");
  if (options?.status) params.set("status", options.status);
  if (options?.extractionMethod) params.set("extraction_method", options.extractionMethod);
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  if (options?.offset !== undefined) params.set("offset", String(options.offset));
  return apiFetch(`/api/career-memory/items?${params.toString()}`);
}

export function updateAgentMemory(
  id: string,
  payload: {
    content?: string;
    memory_type?: AgentMemoryType;
    user_confirmed?: boolean;
    memory_key?: string;
    structured_value?: Record<string, unknown>;
    scope?: string;
    memory_class?: AgentMemoryClass;
    stability?: AgentMemoryStability;
    importance?: number;
    pinned?: boolean;
    valid_until?: string;
  },
): Promise<AgentMemory> {
  return apiFetch<AgentMemory>(`/api/career-memory/items/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteAgentMemory(id: string, permanent = false): Promise<void> {
  return apiFetch<void>(
    `/api/career-memory/items/${encodeURIComponent(id)}?permanent=${permanent}`,
    { method: "DELETE" },
  );
}

export function restoreAgentMemory(id: string): Promise<AgentMemory> {
  return apiFetch<AgentMemory>(`/api/career-memory/items/${encodeURIComponent(id)}/restore`, {
    method: "POST",
  });
}

export function markAgentMemoryOutdated(id: string): Promise<AgentMemory> {
  return apiFetch<AgentMemory>(`/api/career-memory/items/${encodeURIComponent(id)}/outdated`, {
    method: "POST",
  });
}

export function getAgentMemoryHistory(id: string): Promise<AgentMemory[]> {
  return apiFetch<AgentMemory[]>(`/api/career-memory/items/${encodeURIComponent(id)}/history`);
}

export function batchDeleteAgentMemories(ids: string[]): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>("/api/career-memory/batch-delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function clearAgentMemories(permanent = false): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>(`/api/career-memory/items?permanent=${permanent}`, {
    method: "DELETE",
  });
}

export function getAgentMemoryCandidates(options: { limit?: number; offset?: number } = {}): Promise<{
  items: AgentMemoryCandidate[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  return apiFetch(`/api/career-memory/candidates${params.toString() ? `?${params}` : ""}`);
}

export function getAgentMemoryEmbeddingRuns(): Promise<AgentMemoryEmbeddingRun[]> {
  return apiFetch("/api/career-memory/embedding-runs");
}

export function getAgentMemoryEmbeddingHealth(): Promise<AgentMemoryEmbeddingHealth> {
  return apiFetch<AgentMemoryEmbeddingHealth>("/api/career-memory/embedding-health");
}

export function createAgentMemoryEmbeddingRun(
  mode: "full" | "incremental" = "incremental",
): Promise<AgentMemoryEmbeddingRun> {
  return apiFetch<AgentMemoryEmbeddingRun>("/api/career-memory/embedding-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export function runAgentMemoryMaintenance(): Promise<AgentMemoryEmbeddingRun> {
  return apiFetch<AgentMemoryEmbeddingRun>('/api/career-memory/maintenance-runs', {
    method: "POST",
  });
}

export function resolveAgentMemoryMaintenanceAction(
  runId: string,
  payload: {
    action: "merge_duplicate" | "supersede_conflict";
    source_memory_id: string;
    target_memory_id: string;
  },
): Promise<AgentMemoryEmbeddingRun> {
  return apiFetch<AgentMemoryEmbeddingRun>(
    `/api/career-memory/maintenance-runs/${encodeURIComponent(runId)}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function cancelAgentMemoryEmbeddingRun(id: string): Promise<AgentMemoryEmbeddingRun> {
  return apiFetch<AgentMemoryEmbeddingRun>(
    `/api/career-memory/embedding-runs/${encodeURIComponent(id)}/cancel`,
    { method: "POST" },
  );
}

export function retryAgentMemoryEmbeddingRun(id: string): Promise<AgentMemoryEmbeddingRun> {
  return apiFetch<AgentMemoryEmbeddingRun>(
    `/api/career-memory/embedding-runs/${encodeURIComponent(id)}/retry`,
    { method: "POST" },
  );
}

export function resolveAgentMemoryCandidate(id: string, accept: boolean): Promise<AgentMemory | void> {
  return apiFetch(`/api/career-memory/candidates/${encodeURIComponent(id)}/${accept ? "accept" : "reject"}`, {
    method: "POST",
  });
}

export async function downloadAgentMemoryExport(): Promise<void> {
  const payload = await apiFetch<Record<string, unknown>>("/api/career-memory/export");
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `careerpilot-memory-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export type MCPConnection = {
  id: string;
  name: string;
  namespace: string;
  transport: "streamable_http" | "stdio";
  endpoint: string | null;
  command: string | null;
  arguments: string[];
  credentials_configured: boolean;
  credentials_hint: string | null;
  enabled: boolean;
  status: string;
  permission_scopes: string[];
  allowed_tools: string[];
  blocked_tools: string[];
  connect_timeout: number;
  tool_timeout: number;
  last_health_check: string | null;
  created_at: string;
  updated_at: string;
};

export type MCPDiscoveredTool = {
  id: string;
  remote_name: string;
  canonical_name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  schema_hash: string;
  active: boolean;
  last_seen_at: string;
};

export function getMCPConnections(): Promise<MCPConnection[]> {
  return apiFetch<MCPConnection[]>("/api/mcp/connections");
}

export function createMCPConnection(payload: {
  name: string;
  namespace: string;
  transport: "streamable_http";
  endpoint: string;
  credentials?: Record<string, string>;
  permission_scopes: string[];
  allowed_tools: string[];
}): Promise<MCPConnection> {
  return apiFetch<MCPConnection>("/api/mcp/connections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateMCPConnection(id: string, payload: Partial<MCPConnection>): Promise<MCPConnection> {
  return apiFetch<MCPConnection>(`/api/mcp/connections/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteMCPConnection(id: string): Promise<void> {
  return apiFetch<void>(`/api/mcp/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function discoverMCPTools(id: string): Promise<{
  connection: MCPConnection;
  tools: MCPDiscoveredTool[];
  changed: number;
}> {
  return apiFetch(`/api/mcp/connections/${encodeURIComponent(id)}/discover`, { method: "POST" });
}

export type EvaluationDataset = {
  id: string;
  name: string;
  suite: "tool_calling" | "rag_retrieval" | "answer" | "memory";
  version: string;
  label_status: string;
  sha256: string;
  case_count: number;
  created_at: string;
};

export type EvaluationRun = {
  id: string;
  dataset_id: string;
  status: string;
  configuration: Record<string, unknown>;
  result: Record<string, unknown>;
  progress_current: number;
  progress_total: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export function getEvaluationDatasets(): Promise<EvaluationDataset[]> {
  return apiFetch<EvaluationDataset[]>("/api/evaluations/datasets");
}

export function importToolEvaluationSeed(): Promise<EvaluationDataset> {
  return apiFetch<EvaluationDataset>("/api/evaluations/datasets/import-tool-seed", {
    method: "POST",
  });
}

export function importMemoryEvaluationSeed(): Promise<EvaluationDataset> {
  return apiFetch<EvaluationDataset>("/api/evaluations/datasets/import-memory-seed", {
    method: "POST",
  });
}

export function getEvaluationRuns(): Promise<EvaluationRun[]> {
  return apiFetch<EvaluationRun[]>("/api/evaluations/runs");
}

export function getEvaluationRun(id: string): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>(`/api/evaluations/runs/${encodeURIComponent(id)}`);
}

export function createEvaluationRun(payload: {
  dataset_id: string;
  observations: Array<Record<string, unknown>>;
  configuration: Record<string, unknown>;
  require_gold: boolean;
}): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>("/api/evaluations/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateEvaluationRun(id: string, action: "cancel" | "retry"): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>(`/api/evaluations/runs/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
}

export function compareEvaluationRuns(leftId: string, rightId: string): Promise<{
  left: EvaluationRun;
  right: EvaluationRun;
  metric_delta: Record<string, number>;
}> {
  const params = new URLSearchParams({ left_id: leftId, right_id: rightId });
  return apiFetch(`/api/evaluations/compare?${params.toString()}`);
}

export type RagV2Query = {
  query_id: string;
  query: string;
  normalized_intent: string;
  query_type: string;
  target_role: string[];
  target_skills: string[];
  hard_constraints: Record<string, unknown>;
  soft_preferences: Record<string, unknown>;
  answerability: "answerable" | "unanswerable" | "uncertain";
  source: string;
  generator_model: string | null;
  requires_human_review: boolean;
  template_group: string;
  split: "train" | "dev" | "test" | null;
  candidate_count?: number;
  annotated_count?: number;
  submitted_count?: number;
};

export type RagV2Job = {
  dataset_version: string;
  job_id: string;
  platform: string;
  external_job_id: string | null;
  title: string;
  company: string;
  description: string;
  location: string;
  city: string;
  salary_min: number | null;
  salary_max: number | null;
  job_type: string;
  education_requirement: string;
  experience_requirement: string;
  education_level: string;
  experience_level: string;
  role_direction: string;
  source_url: string | null;
};

export type RagV2Annotation = {
  annotation_id?: string | null;
  dataset_version: string;
  query_id: string;
  job_id: string;
  annotator_id: string;
  relevance_grade: -1 | 0 | 1 | 2 | 3;
  hard_constraint_violation: "yes" | "no" | "uncertain";
  answerability_judgment?: "answerable" | "unanswerable" | "uncertain" | null;
  matched_requirements: string[];
  missing_requirements: string[];
  evidence_spans: Array<{ start: number; end: number; text: string; section?: string | null }>;
  confidence: "low" | "medium" | "high";
  annotation_note: string;
  status: "draft" | "submitted" | "skipped";
  updated_at?: string;
};

export type RagV2QueryDetail = {
  query: RagV2Query;
  items: Array<{ job: RagV2Job; candidate_rank: number; channels: string[]; annotation: RagV2Annotation | null }>;
  labeler_view: { model_scores: boolean };
};

export type RagV2Status = {
  dataset_version: string;
  label_status: string;
  corpus_sha256: string | null;
  source_job_count: number;
  selected_job_count: number;
  query_count: number;
  candidate_pair_count: number;
  annotation_quality: Record<string, number | boolean | null>;
  progress: Record<string, Record<string, number | string>>;
};

export function getRagV2Status(): Promise<RagV2Status> {
  return apiFetch<RagV2Status>("/api/evaluation-v2/status");
}

export function getRagV2Queries(annotatorId: string): Promise<RagV2Query[]> {
  return apiFetch<RagV2Query[]>(`/api/evaluation-v2/queries?annotator_id=${encodeURIComponent(annotatorId)}`);
}

export function getRagV2Query(queryId: string, annotatorId: string): Promise<RagV2QueryDetail> {
  return apiFetch<RagV2QueryDetail>(`/api/evaluation-v2/queries/${encodeURIComponent(queryId)}?annotator_id=${encodeURIComponent(annotatorId)}`);
}

export function saveRagV2Annotation(payload: RagV2Annotation): Promise<RagV2Annotation> {
  return apiFetch<RagV2Annotation>("/api/evaluation-v2/annotations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getCareerAdvisorSessions(options?: { limit?: number; offset?: number }): Promise<CareerAdvisorSessionListResponse> {
  const params = new URLSearchParams();
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  if (options?.offset !== undefined) params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<CareerAdvisorSessionListResponse>(`/api/career-advisor/sessions${query ? `?${query}` : ""}`);
}

export function getCareerAdvisorSession(
  id: string,
  options?: { limit?: number; offset?: number },
): Promise<CareerAdvisorSession> {
  const params = new URLSearchParams();
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  if (options?.offset !== undefined) params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<CareerAdvisorSession>(`/api/career-advisor/sessions/${encodeURIComponent(id)}${query ? `?${query}` : ""}`);
}

export function createCareerAdvisorSession(payload?: {
  title?: string;
  resume_id?: string | null;
  context_filters?: JobKnowledgeFilters;
}): Promise<CareerAdvisorSession> {
  return apiFetch<CareerAdvisorSession>("/api/career-advisor/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
}

export function updateCareerAdvisorSession(
  id: string,
  payload: {
    title?: string;
    resume_id?: string | null;
    context_filters?: JobKnowledgeFilters;
  },
): Promise<CareerAdvisorSession> {
  return apiFetch<CareerAdvisorSession>(`/api/career-advisor/sessions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteCareerAdvisorSession(id: string): Promise<void> {
  return apiFetch<void>(`/api/career-advisor/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function sendCareerAdvisorMessage(
  sessionId: string,
  payload: { content: string; resume_id?: string | null; filters?: JobKnowledgeFilters | null },
): Promise<CareerAdvisorMessage> {
  return apiFetch<CareerAdvisorMessage>(`/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function bindCareerAdvisorSessionJobs(
  sessionId: string,
  payload: {
    message_id: string;
    job_ids: string[];
    source_type?: "automated_collection" | "knowledge_base";
    context?: Record<string, unknown>;
  },
): Promise<CareerAdvisorSessionJobsBindResponse> {
  return apiFetch<CareerAdvisorSessionJobsBindResponse>(
    `/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/jobs/bind`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function cancelCareerAdvisorMessage(messageId: string): Promise<CareerAdvisorMessage> {
  return apiFetch<CareerAdvisorMessage>(`/api/career-advisor/messages/${encodeURIComponent(messageId)}/cancel`, {
    method: "POST",
  });
}

export function regenerateCareerAdvisorMessage(messageId: string): Promise<CareerAdvisorMessage> {
  return apiFetch<CareerAdvisorMessage>(`/api/career-advisor/messages/${encodeURIComponent(messageId)}/regenerate`, {
    method: "POST",
  });
}

export function getCareerAdvisorCitations(messageId: string): Promise<CareerAdvisorCitationListResponse> {
  return apiFetch<CareerAdvisorCitationListResponse>(`/api/career-advisor/messages/${encodeURIComponent(messageId)}/citations`);
}

export function prepareCareerAdvisorApplication(
  sessionId: string,
  payload: { message_id: string; job_ids: string[]; resume_id?: string | null; plan_name?: string; message?: string },
): Promise<{ message_id: string; ui_action: CareerAdvisorUiAction }> {
  return apiFetch(`/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/actions/prepare-application`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function confirmCareerAdvisorApplication(
  sessionId: string,
  payload: { message_id: string; campaign_id: string; confirmation_token: string },
): Promise<{ message_id: string; ui_action: CareerAdvisorUiAction }> {
  return apiFetch(`/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/actions/confirm-application`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getCareerAdvisorApplicationProgress(
  sessionId: string,
  payload: { message_id: string; campaign_id: string },
): Promise<{ message_id: string; ui_action: CareerAdvisorUiAction }> {
  return apiFetch(`/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/actions/application-progress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function cancelCareerAdvisorApplication(
  sessionId: string,
  payload: { message_id: string; campaign_id: string },
): Promise<{ message_id: string; ui_action: CareerAdvisorUiAction }> {
  return apiFetch(`/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/actions/cancel-application`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

type CareerAdvisorStreamPayload = {
  content?: string;
  resume_id?: string | null;
  filters?: JobKnowledgeFilters | null;
  job_ids?: string[];
  collection_key?: string;
};

export type CareerAdvisorStreamConnectionState = "connected" | "reconnecting" | "recovered" | "offline";
type CareerAdvisorStreamConnectionCallback = (state: CareerAdvisorStreamConnectionState, attempt?: number) => void;

async function streamCareerAdvisorResponse(
  url: string,
  payload: CareerAdvisorStreamPayload,
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
  onConnectionChange?: CareerAdvisorStreamConnectionCallback,
  method: "GET" | "POST" = "POST",
): Promise<CareerAdvisorMessage> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${url}`, {
      method,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: method === "GET" ? undefined : JSON.stringify(payload),
      cache: "no-store",
      signal,
    });
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
    onConnectionChange?.("reconnecting");
    throw new Error("无法连接 API 服务，请确认后端已启动并稍后重试。");
  }
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
  if (!response.body) throw new Error("职业顾问暂时无法建立流式连接。");
  onConnectionChange?.("connected");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventType = "message";
  let eventData: string[] = [];
  let finalMessage: CareerAdvisorMessage | null = null;

  const dispatch = () => {
    if (!eventData.length) return;
    const raw = eventData.join("\n");
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      parsed = { content: raw };
    }
    onEvent(eventType, parsed);
    if (eventType === "message_state") finalMessage = parsed as unknown as CareerAdvisorMessage;
    eventType = "message";
    eventData = [];
  };

  const consumeLine = (line: string) => {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) eventData.push(line.slice(5).trimStart());
    else if (!line.trim()) dispatch();
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";
      lines.forEach(consumeLine);
      if (done) break;
    }
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
    onConnectionChange?.("reconnecting");
    throw reason instanceof Error ? reason : new Error("职业顾问流式连接已中断。");
  }
  if (buffer) consumeLine(buffer);
  dispatch();
  if (!finalMessage) throw new Error("职业顾问未返回完整结果，请稍后重试。");
  return finalMessage;
}

export function streamCareerAdvisorMessage(
  sessionId: string,
  payload: { content: string; resume_id?: string | null; filters?: JobKnowledgeFilters | null },
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
  onConnectionChange?: CareerAdvisorStreamConnectionCallback,
): Promise<CareerAdvisorMessage> {
  return streamCareerAdvisorResponse(
    `/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/messages/stream`,
    payload,
    onEvent,
    signal,
    onConnectionChange,
  );
}

export function streamCareerAdvisorRecovery(
  messageId: string,
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
  onConnectionChange?: CareerAdvisorStreamConnectionCallback,
): Promise<CareerAdvisorMessage> {
  return streamCareerAdvisorResponse(
    `/api/career-advisor/messages/${encodeURIComponent(messageId)}/stream`,
    {},
    onEvent,
    signal,
    onConnectionChange,
    "GET",
  );
}

export function streamCareerAdvisorCollectionContinuation(
  sessionId: string,
  messageId: string,
  payload: { job_ids: string[]; collection_key?: string },
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
  onConnectionChange?: CareerAdvisorStreamConnectionCallback,
): Promise<CareerAdvisorMessage> {
  return streamCareerAdvisorResponse(
    `/api/career-advisor/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}/collection-complete/stream`,
    payload,
    onEvent,
    signal,
    onConnectionChange,
  );
}

export function streamRegenerateCareerAdvisorMessage(
  messageId: string,
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
  onConnectionChange?: CareerAdvisorStreamConnectionCallback,
): Promise<CareerAdvisorMessage> {
  return streamCareerAdvisorResponse(
    `/api/career-advisor/messages/${encodeURIComponent(messageId)}/regenerate/stream`,
    {},
    onEvent,
    signal,
    onConnectionChange,
  );
}

export type KnowledgeIndexRun = {
  id: string;
  mode: "incremental" | "backfill" | string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | string;
  stage: string;
  progress: number;
  total_jobs: number;
  processed_jobs: number;
  succeeded_jobs: number;
  skipped_jobs: number;
  failed_jobs: number;
  current_job_id: string | null;
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type KnowledgeIndexRunListResponse = {
  items: KnowledgeIndexRun[];
  total: number;
};

export function getKnowledgeIndexRuns(): Promise<KnowledgeIndexRunListResponse> {
  return apiFetch<KnowledgeIndexRunListResponse>("/api/knowledge/index-runs");
}

export type KnowledgeHealth = {
  status: "not_built" | "partial" | "needs_update" | "ready";
  ready: boolean; jobs_total: number; document_count: number; indexed_jobs: number;
  compatible_jobs: number; needs_update_jobs: number; chunk_count: number;
  embedded_chunk_count?: number; coverage_percent?: number; embedding_model?: string;
  embedding_dimensions?: number; updated_at: string | null;
  latest_run: Pick<KnowledgeIndexRun, "id" | "status" | "progress" | "processed_jobs" | "total_jobs" | "error"> | null;
};

export function getKnowledgeHealth(): Promise<KnowledgeHealth> {
  return apiFetch<KnowledgeHealth>("/api/knowledge/status");
}

export function createKnowledgeIndexRun(payload: {
  mode: "incremental" | "backfill";
  job_ids?: string[];
  force?: boolean;
  auto_start?: boolean;
}): Promise<KnowledgeIndexRun> {
  return apiFetch<KnowledgeIndexRun>("/api/knowledge/index-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
