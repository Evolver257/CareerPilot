import type { Job } from "./api";

export const AUTO_DELIVERY_MAX_JOB_AGE_DAYS = 3;
const MAX_AGE_MS = AUTO_DELIVERY_MAX_JOB_AGE_DAYS * 24 * 60 * 60 * 1000;

export function isJobFreshForAutoDelivery(
  job: Pick<Job, "last_collected_at">,
  now = Date.now(),
): boolean {
  const collectedAt = new Date(job.last_collected_at).getTime();
  return Number.isFinite(collectedAt) && collectedAt >= now - MAX_AGE_MS;
}

export function formatJobCollectionTime(job: Pick<Job, "last_collected_at">): string {
  const collectedAt = new Date(job.last_collected_at);
  return Number.isNaN(collectedAt.getTime())
    ? "采集时间未知"
    : collectedAt.toLocaleString("zh-CN");
}
