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
