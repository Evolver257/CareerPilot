export type ZhaopinVisibleJob = {
  external_job_id: string; title: string; description: string; job_url: string;
  location: string | null; company_name: string | null; salary_text: string | null;
  experience: string | null; education: string | null;
  requirements: string[]; skills: string[]; benefits: string[];
  raw_data: Record<string, unknown>;
};
export type ZhaopinPageState = "READY" | "CAPTCHA" | "LOGIN_REQUIRED" | "PLATFORM_LIMIT" | "RISK_CONTROL" | "DOM_CHANGED" | "TAB_HIDDEN" | "UNKNOWN_STATE";
const HOSTS = new Set(["zhaopin.com", "www.zhaopin.com", "sou.zhaopin.com", "m.zhaopin.com"]);
// Verified against the public /sou/ and /jobdetail/*.htm DOM on 2026-09-04.
const CARDS = ".joblist-box__item, .job-list-item, .job-card, .job-item, .position-item, [data-job-id], [data-position-id], [data-zwid]";
const DETAIL = ".describtion-card__detail-content, .job-description, .job-desc, .describtion__detail-content";
const EDUCATION = /博士|硕士|研究生|本科|大专|专科|高中|中专|学历不限/;
const EXPERIENCE = /\d+\s*[-–~至]\s*\d+年|\d+年以上|经验不限|无经验|应届|在校/;

export function isZhaopinPageUrl(value = window.location.href): boolean {
  try { const url = new URL(value); return url.protocol === "https:" && HOSTS.has(url.hostname); } catch { return false; }
}
export function isZhaopinSearchUrl(value: string): boolean {
  return isZhaopinPageUrl(value) && /^\/(sou(?:\/|$)|web\/search\/?$)/.test(new URL(value).pathname);
}
export function zhaopinJobId(value: string): string | null {
  try {
    const url = new URL(value);
    if (!HOSTS.has(url.hostname) || !["http:", "https:"].includes(url.protocol)) return null;
    return url.pathname.match(/^\/(?:jobdetail|jobs|job|position|zw)\/([\w-]+)\.html?$/i)?.[1] ?? null;
  } catch { return null; }
}
function jobLink(root: ParentNode): HTMLAnchorElement | undefined {
  return [...root.querySelectorAll<HTMLAnchorElement>("a[href]")].find((a) => zhaopinJobId(a.href));
}
function visible(el: Element): boolean {
  for (let node: Element | null = el; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden" || node.hasAttribute("hidden")) return false;
  }
  return el.getBoundingClientRect().height > 0;
}
function clean(value: string): string { return value.replace(/[\t \u00a0]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim(); }
function text(el: Element | null): string {
  if (!el) return "";
  if ((el as HTMLElement).innerText) return clean((el as HTMLElement).innerText);
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll("script, style, [hidden]").forEach((node) => node.remove());
  copy.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
  copy.querySelectorAll("p, div, li, h2, h3, h4").forEach((node) => node.append("\n"));
  return clean(copy.textContent || "");
}
function first(root: ParentNode, selectors: string[]): string | null {
  for (const selector of selectors) { const value = text(root.querySelector(selector)); if (value) return value; }
  return null;
}
function texts(root: ParentNode, selector: string): string[] {
  return [...new Set([...root.querySelectorAll(selector)].map(text).filter(Boolean))].slice(0, 50);
}
function cards(): HTMLElement[] {
  const found = [...document.querySelectorAll<HTMLElement>(CARDS)].filter((el) => visible(el) && jobLink(el));
  return found.filter((el) => !found.some((other) => other !== el && el.contains(other)));
}
export function detectZhaopinPageState(): ZhaopinPageState {
  if (!isZhaopinPageUrl()) return "UNKNOWN_STATE";
  if (document.hidden) return "TAB_HIDDEN";
  const hasJob = Boolean(document.querySelector(".summary-planes__title")) || cards().length > 0;
  const overlays = [...document.querySelectorAll("[role='dialog'], .geetest_panel, .geetest_panel_box, .captcha-container, .verify-dialog, .login-dialog, .login-modal")].filter(visible);
  const signal = overlays.map(text).join("\n") + (hasJob ? "" : document.title + "\n" + text(document.body));
  if (/验证码|人机验证|滑块验证|captcha/i.test(signal)) return "CAPTCHA";
  if (/访问频繁|操作频繁|请求过于频繁/.test(signal)) return "PLATFORM_LIMIT";
  if (/安全验证|风险验证|异常访问|账号存在风险/.test(signal)) return "RISK_CONTROL";
  if (/请先登录|登录后继续|扫码登录|登录后查看/.test(signal)) return "LOGIN_REQUIRED";
  return hasJob || document.querySelector(DETAIL) ? "READY" : "UNKNOWN_STATE";
}
export function extractZhaopinDetail(expectedId?: string): ZhaopinVisibleJob | null {
  const id = zhaopinJobId(window.location.href);
  if (!id || (expectedId && id !== expectedId)) return null;
  const title = first(document, [".summary-planes__title", "h1"]);
  const description = first(document, DETAIL.split(", "));
  if (!title || !description) return null;
  const info = texts(document, ".summary-planes__info > li");
  const salary = first(document, [".summary-planes__salary", ".job-salary"]);
  const requirements = description.split(/(?:任职要求|任职资格|任职条件|岗位要求|岗位基本需求|岗位基本要求|基本要求|资格要求|职位要求)[：:]?/)[1]?.split(/补充说明|福利待遇|工作地点|岗位亮点/)[0]?.split("\n").filter(Boolean).slice(0, 50) ?? [];
  return {
    external_job_id: id, title, description: description.slice(0, 20_000), job_url: canonical(window.location.href),
    location: info[0] ?? first(document, [".work-location", ".job-location"]),
    company_name: first(document, [".company-info__name", ".company__title", ".company-name"]),
    salary_text: salary && !/[*＊]|查看薪资/.test(salary) ? salary : null,
    education: info.find((value) => EDUCATION.test(value)) ?? null,
    experience: info.find((value) => EXPERIENCE.test(value)) ?? null,
    requirements, skills: texts(document, ".describtion-card__skills-item"),
    benefits: texts(document, ".summary-planes__welfare span, .job-welfare span"),
    raw_data: {
      description_source: "detail_page", detail_url: canonical(window.location.href), parser_version: "zhaopin-dom-2026-09-04",
      salary_visibility: salary && /[*＊]|查看薪资/.test(salary) ? "masked" : "visible",
      company_description: first(document, [".company-info__intro"]),
      company_summary: first(document, [".company-info__desc"]),
      work_address: first(document, [".address-info__text", ".address-info__bubble"]),
    },
  };
}
function canonical(value: string): string { const url = new URL(value); url.protocol = "https:"; url.search = ""; url.hash = ""; return url.toString(); }
export function extractVisibleZhaopinJobs(): ZhaopinVisibleJob[] {
  if (!isZhaopinPageUrl()) return [];
  // Recommendations below a detail page must never override the requested job.
  if (zhaopinJobId(window.location.href)) { const detail = extractZhaopinDetail(); return detail ? [detail] : []; }
  if (!isZhaopinSearchUrl(window.location.href)) return [];
  const jobs = cards().flatMap((card): ZhaopinVisibleJob[] => {
    const link = jobLink(card)!; const id = zhaopinJobId(link.href)!;
    const title = first(card, [".jobinfo__name", ".job-title", ".job-name", ".position-name", "[data-role='title']"]) || text(link);
    if (!title) return [];
    const info = texts(card, ".jobinfo__other-info-item");
    return [{
      external_job_id: id, title, job_url: canonical(link.href),
      description: first(card, [".job-desc", ".job-description"]) || title,
      company_name: first(card, [".companyinfo__name", ".company-name", ".com-name"]),
      salary_text: first(card, [".jobinfo__salary", ".salary", ".job-salary"]),
      location: info[0] ?? first(card, [".job-location", ".location"]),
      experience: info.find((value) => EXPERIENCE.test(value)) ?? first(card, [".experience"]),
      education: info.find((value) => EDUCATION.test(value)) ?? first(card, [".education"]),
      requirements: [], skills: texts(card, ".jobinfo__tag .joblist-box__item-tag"), benefits: [],
      raw_data: { description_source: "card_summary", search_page_url: window.location.href },
    }];
  });
  return [...new Map(jobs.map((job) => [job.external_job_id, job])).values()];
}
export function mergeZhaopinDetail(card: ZhaopinVisibleJob, detail: ZhaopinVisibleJob): ZhaopinVisibleJob {
  if (card.external_job_id !== detail.external_job_id) throw new Error("职位详情编号不匹配，已停止采集");
  return { ...detail, company_name: detail.company_name || card.company_name,
    salary_text: detail.salary_text || card.salary_text, location: detail.location || card.location,
    education: detail.education || card.education, experience: detail.experience || card.experience,
    skills: [...new Set([...detail.skills, ...card.skills])].slice(0, 50),
    raw_data: { ...card.raw_data, ...detail.raw_data, salary_source: detail.salary_text ? "detail_page" : card.salary_text ? "search_card" : "unavailable" },
  };
}
export async function advanceZhaopinSearch(): Promise<{ next_url?: string; advanced: boolean }> {
  if (!isZhaopinSearchUrl(window.location.href) || detectZhaopinPageState() !== "READY") return { advanced: false };
  const original = extractVisibleZhaopinJobs().map((job) => job.external_job_id).join(",");
  cards().at(-1)?.scrollIntoView({ block: "end", behavior: "instant" });
  const scrolling = document.scrollingElement;
  if (scrolling) scrolling.scrollTop = scrolling.scrollHeight;
  for (let attempt = 0; attempt < 5; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (extractVisibleZhaopinJobs().map((job) => job.external_job_id).join(",") !== original) return { advanced: true };
  }
  const next = [...document.querySelectorAll<HTMLElement>("a, button, [role='button'], .soupager__btn")].find((el) => (
    visible(el) && (text(el).trim() === "下一页" || el.getAttribute("aria-label") === "下一页" || el.getAttribute("rel") === "next")
    && !el.matches(":disabled, [disabled], [aria-disabled='true'], .disabled") && !/disabled/.test(el.className)
  ));
  if (!next) return { advanced: false };
  const href = next instanceof HTMLAnchorElement ? next.href : "";
  if (href && isZhaopinSearchUrl(href) && href !== window.location.href) return { advanced: true, next_url: href };
  next.click(); return { advanced: true };
}
