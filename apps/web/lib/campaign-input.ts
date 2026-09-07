export function parseCampaignNumbers(maxJobs: string, minScore: string) {
  const max_jobs = Number(maxJobs);
  const min_score = Number(minScore);
  if (!maxJobs.trim() || !Number.isInteger(max_jobs) || max_jobs < 1 || max_jobs > 200) {
    throw new Error("最多职位数请输入 1–200 的整数。");
  }
  if (!minScore.trim() || !Number.isFinite(min_score) || min_score < 0 || min_score > 100) {
    throw new Error("最低匹配分数请输入 0–100 的数字。");
  }
  return { max_jobs, min_score };
}
