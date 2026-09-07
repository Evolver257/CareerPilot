import type { Job, JobAnalysis } from "./api";

export function rawJobText(job: Job, key: string): string | null {
  const nested = job.raw_data.raw_data;
  const legacy = nested && typeof nested === "object" ? nested as Record<string, unknown> : {};
  for (const value of [job.raw_data[key], legacy[key], job.platform_metadata?.[key]]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}
export function rawJobList(job: Job, key: string): string[] {
  const value = job.raw_data[key];
  return Array.isArray(value) ? [...new Set(value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean))] : [];
}
export function jobPlatformLabel(platform: string): string {
  return ({ boss: "BOSS 直聘", zhaopin: "智联招聘", manual: "手动录入", mock: "演示平台" } as Record<string, string>)[platform] || platform;
}
export function jobEducation(job: Job, analysis?: JobAnalysis | null): string {
  return (job.platform === "zhaopin" ? rawJobText(job, "education") : null)
    || job.education_requirement || analysis?.requirements.education || "未注明";
}
export function jobExperience(job: Job, analysis?: JobAnalysis | null): string {
  return (job.platform === "zhaopin" ? rawJobText(job, "experience") : null)
    || job.experience_requirement || analysis?.requirements.experience || "未注明";
}
export function jobSalary(job: Job, analysis?: JobAnalysis | null): string {
  const captured = rawJobText(job, "salary_text");
  if (captured && !/[*＊\uE000-\uF8FF]|查看薪资/.test(captured)) return captured;
  if (job.platform === "zhaopin" && (captured || rawJobText(job, "salary_visibility") === "masked")) return "薪资未公开";
  const min = job.salary_min ?? analysis?.structured_job.salary.minimum;
  const max = job.salary_max ?? analysis?.structured_job.salary.maximum;
  const range = min != null && max != null ? `${min} - ${max}` : min != null ? `${min}+` : max != null ? `最高 ${max}` : null;
  return range ? range + (job.platform === "zhaopin" ? "（单位未注明）" : "") : job.platform === "zhaopin" ? "薪资未注明" : "薪资面议";
}
export function jobDescription(job: Job): string {
  if (job.platform !== "zhaopin") return job.description;
  // Remove only the import-generated prefix. User edits to the current JD take priority over raw snapshots.
  const lines = job.description.trim().split(/\r?\n/);
  if (lines[0]?.trim() === job.title.trim()) lines.shift();
  while (lines.length && /^(?:Company|Location|Salary|Experience|Education):\s*/.test(lines[0])) lines.shift();
  return lines.join("\n").trim() || job.description;
}
export function readableJobMarkdown(description: string): string {
  return description.split(/\r?\n/).map((line) => {
    const heading = line.trim().replace(/^[一二三四五六七八九十\d]+[、.．]\s*/, "").replace(/[：:]$/, "").replace(/^[【\[]|[】\]]$/g, "");
    if (/^(工作职责|岗位职责|职位描述|任职要求|任职资格|任职条件|岗位要求|岗位基本需求|岗位基本要求|基本要求|资格要求|职位要求|加分项|优先条件|福利待遇|岗位亮点|补充说明)$/.test(heading)) return "## " + heading;
    return line.replace(/^(\s*)(\d+)[、．.）)]\s*(\S)/, "$1$2. $3");
  }).join("\n");
}
