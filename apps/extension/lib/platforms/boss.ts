export type BossVisibleJob = {
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

export type BossPageState =
  | "READY"
  | "CAPTCHA"
  | "LOGIN_REQUIRED"
  | "PLATFORM_LIMIT"
  | "RISK_CONTROL"
  | "DOM_CHANGED"
  | "UNKNOWN_STATE";

const BOSS_HOSTS = new Set(["zhipin.com", "www.zhipin.com", "m.zhipin.com"]);
const CARD_SELECTORS = [
  ".job-card-wrap",
  ".job-card-wrapper",
  ".job-card-box",
  ".card-area",
  ".job-card",
  "[data-jobid]",
  "[data-job-id]",
];
const TITLE_SELECTORS = [".job-name", ".job-title", "[data-job-title]"];
const COMPANY_SELECTORS = [".boss-name", ".company-name", ".company-text", ".company-info"];
const LOCATION_SELECTORS = [".company-location", ".job-area", ".job-location", ".job-card-location"];
const SALARY_SELECTORS = [".salary", ".job-salary", ".job-card-salary"];
const DETAIL_DESCRIPTION_SELECTORS = [
  ".job-detail-box .job-detail-body .desc",
  ".job-detail-box .job-detail-body",
  ".job-detail-container .job-detail-body",
  ".job-sec-text",
  ".job-detail",
  ".detail-content",
];
const DETAIL_TITLE_SELECTORS = [
  ".job-detail-box .job-detail-info .job-name",
  ".job-detail-container .job-name",
  ".job-detail-box .job-name",
];
const JOB_LIST_SELECTORS = [
  ".job-list-container",
  ".job-list-box",
  ".job-list-wrapper",
  ".job-card-list",
  ".search-job-result",
  ".job-list",
];
const MAX_VISIBLE_JOBS = 50;
const MAX_SCROLL_ROUNDS = 20;
const MAX_STAGNANT_SCROLLS = 3;

const CITY_CODES: Record<string, string> = {
  北京: "101010100",
  上海: "101020100",
  广州: "101280100",
  深圳: "101280600",
  杭州: "101210100",
  南京: "101190100",
  成都: "101270100",
  武汉: "101200100",
  西安: "101110100",
  苏州: "101190400",
};

export function buildBossSearchUrl(requirements: string, city: string): string {
  const normalizedRequirements = requirements.trim();
  const normalizedCity = city.trim();
  const cityCode = CITY_CODES[normalizedCity];
  const query = cityCode || !normalizedCity
    ? normalizedRequirements
    : `${normalizedRequirements} ${normalizedCity}`.trim();
  const url = new URL("https://www.zhipin.com/web/geek/jobs");
  url.searchParams.set("query", query);
  if (cityCode) url.searchParams.set("city", cityCode);
  return url.toString();
}

export function isBossPageUrl(url = window.location.href): boolean {
  try {
    return BOSS_HOSTS.has(new URL(url).hostname.toLocaleLowerCase());
  } catch {
    return false;
  }
}

export function detectBossPageState(): BossPageState {
  if (!isBossPageUrl()) return "UNKNOWN_STATE";
  const content = `${document.title}\n${document.body.innerText}`.toLocaleLowerCase();
  if (["验证码", "人机验证", "captcha", "图形验证"].some((marker) => content.includes(marker))) return "CAPTCHA";
  if (["请先登录", "登录后", "登录/注册", "登录注册"].some((marker) => content.includes(marker))) return "LOGIN_REQUIRED";
  if (["操作频繁", "访问频繁", "platform limit"].some((marker) => content.includes(marker))) return "PLATFORM_LIMIT";
  if (["安全验证", "风控", "risk control"].some((marker) => content.includes(marker))) return "RISK_CONTROL";
  if (["职位搜索", "职位详情", "立即沟通", "立即投递", "薪资"].some((marker) => content.includes(marker))) return "READY";
  return "UNKNOWN_STATE";
}

export function extractVisibleBossJobs(): BossVisibleJob[] {
  if (!isBossPageUrl()) return [];
  const cards = uniqueVisibleElements(CARD_SELECTORS.flatMap((selector) => [...document.querySelectorAll<HTMLElement>(selector)]));
  const jobs = cards.map((card) => extractCard(card)).filter((job): job is BossVisibleJob => job !== null);
  if (jobs.length > 0) return dedupe(jobs);

  const detailTitle = readFirst(document, TITLE_SELECTORS) || document.querySelector("h1")?.textContent?.trim() || "";
  const externalJobId = extractJobId(window.location.href);
  if (!detailTitle || !externalJobId) return [];
  const description = normalizeDescription(
    document.querySelector<HTMLElement>(".job-sec-text, .job-detail, .detail-content")?.innerText
      || document.body.innerText,
  );
  return [{
    external_job_id: externalJobId,
    title: detailTitle,
    description: description || detailTitle,
    job_url: window.location.href,
    location: readFirst(document, LOCATION_SELECTORS),
    company_name: readFirst(document, COMPANY_SELECTORS),
    salary_text: readSalary(document),
    tags: [],
    description_source: "detail_panel",
  }];
}

export async function extractVisibleBossJobsWithDetails(maxJobs = 20): Promise<BossVisibleJob[]> {
  const limit = Math.min(Math.max(maxJobs, 1), MAX_VISIBLE_JOBS);
  const collected = new Map<string, BossVisibleJob>();
  let stagnantScrolls = 0;

  for (let round = 0; round < MAX_SCROLL_ROUNDS && collected.size < limit; round += 1) {
    if (detectBossPageState() !== "READY") break;
    const cards = visibleJobCards();

    for (const card of cards) {
      if (collected.size >= limit) break;
      const job = extractCard(card);
      if (!job || collected.has(job.external_job_id)) continue;

      let enriched = job;
      if (job.description_source !== "detail_panel" && card.isConnected) {
        const clickTarget = card.querySelector<HTMLElement>(".job-card-box") ?? card;
        clickTarget.click();
        const detailDescription = await waitForJobDetail(job.title, card);
        if (detailDescription) {
          enriched = {
            ...job,
            description: detailDescription,
            description_source: "detail_panel",
          };
        }
      }
      collected.set(enriched.external_job_id, enriched);
    }

    if (collected.size >= limit || detectBossPageState() !== "READY") break;
    const knownJobIds = new Set(collected.keys());
    const scrollTarget = findJobListScrollTarget(cards);
    scrollJobList(scrollTarget, cards);
    const foundNewCards = await waitForNewJobCards(knownJobIds);
    stagnantScrolls = foundNewCards ? 0 : stagnantScrolls + 1;
    if (stagnantScrolls >= MAX_STAGNANT_SCROLLS) break;
  }

  return [...collected.values()].slice(0, limit);
}

function extractCard(card: HTMLElement): BossVisibleJob | null {
  const link = card.querySelector<HTMLAnchorElement>("a[href*='/job_detail/'], a.job-name, a.job-card-left");
  const jobUrl = link?.href || window.location.href;
  const externalJobId = card.dataset.jobid || card.dataset.jobId || extractJobId(jobUrl);
  const title = readFirst(card, TITLE_SELECTORS);
  if (!externalJobId || !title) return null;
  const activeCard = isActiveCard(card);
  const detailDescription = activeCard ? readDescription(document) : null;
  const description = detailDescription || normalize(card.innerText) || title;
  const tags = [...card.querySelectorAll<HTMLElement>(".tag-list li, .job-label-list li, [class*='tag']")].map((element) => normalize(element.innerText)).filter(Boolean).slice(0, 20);
  return {
    external_job_id: externalJobId,
    title,
    description,
    job_url: jobUrl,
    location: readFirst(card, LOCATION_SELECTORS),
    company_name: readFirst(card, COMPANY_SELECTORS),
    salary_text: readSalary(card),
    tags,
    description_source: detailDescription ? "detail_panel" : "card_summary",
  };
}

function visibleJobCards(): HTMLElement[] {
  return uniqueVisibleElements(
    CARD_SELECTORS.flatMap((selector) => [...document.querySelectorAll<HTMLElement>(selector)]),
  );
}

function findJobListScrollTarget(cards: HTMLElement[]): HTMLElement | null {
  for (const selector of JOB_LIST_SELECTORS) {
    const candidate = document.querySelector<HTMLElement>(selector);
    if (candidate && isScrollable(candidate)) return candidate;
  }

  let ancestor = cards[0]?.parentElement ?? null;
  while (ancestor && ancestor !== document.body && ancestor !== document.documentElement) {
    if (isScrollable(ancestor)) return ancestor;
    ancestor = ancestor.parentElement;
  }

  const scrollingElement = document.scrollingElement;
  return scrollingElement instanceof HTMLElement ? scrollingElement : document.documentElement;
}

function isScrollable(element: HTMLElement): boolean {
  if (element.scrollHeight <= element.clientHeight + 24) return false;
  const overflowY = window.getComputedStyle(element).overflowY;
  return ["auto", "scroll", "overlay"].includes(overflowY);
}

function scrollJobList(target: HTMLElement | null, cards: HTMLElement[]): void {
  if (!target) return;
  const previousTop = target.scrollTop;
  const distance = Math.max(Math.round(target.clientHeight * 0.8), 480);
  const nextTop = Math.min(previousTop + distance, target.scrollHeight);
  target.scrollTo({ top: nextTop, behavior: "instant" });
  target.dispatchEvent(new Event("scroll", { bubbles: true }));

  if (target.scrollTop <= previousTop) {
    cards.at(-1)?.scrollIntoView({ block: "end", behavior: "instant" });
  }
}

async function waitForNewJobCards(knownJobIds: Set<string>): Promise<boolean> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 1800) {
    await new Promise((resolve) => window.setTimeout(resolve, 200));
    if (detectBossPageState() !== "READY") return false;
    const hasNewCard = visibleJobCards().some((card) => {
      const job = extractCard(card);
      return Boolean(job && !knownJobIds.has(job.external_job_id));
    });
    if (hasNewCard) return true;
  }
  return false;
}

async function waitForJobDetail(title: string, card: HTMLElement): Promise<string | null> {
  const expectedTitle = normalize(title).toLocaleLowerCase();
  const startedAt = Date.now();
  while (Date.now() - startedAt < 2500) {
    await new Promise((resolve) => window.setTimeout(resolve, 150));
    const detailTitle = (readFirst(document, DETAIL_TITLE_SELECTORS) ?? "").toLocaleLowerCase();
    const description = readDescription(document);
    if ((!card.isConnected || isActiveCard(card)) && description && description.length >= 20 && (
      !detailTitle || detailTitle.includes(expectedTitle) || expectedTitle.includes(detailTitle)
    )) {
      return description;
    }
  }
  return null;
}

function isActiveCard(card: HTMLElement): boolean {
  return card.matches(".active")
    || Boolean(card.closest(".job-card-wrap.active, .job-card-wrapper.active, .card-area.active"));
}

function readDescription(root: ParentNode): string | null {
  for (const selector of DETAIL_DESCRIPTION_SELECTORS) {
    const element = root.querySelector<HTMLElement>(selector);
    if (element && isVisible(element)) {
      const text = normalizeDescription(element.innerText || element.textContent || "");
      if (text) return text.slice(0, 20_000);
    }
  }
  return null;
}

function readSalary(root: ParentNode): string | null {
  const salary = readFirst(root, SALARY_SELECTORS);
  return salary ? decodeBossSalary(salary) : null;
}

export function decodeBossSalary(value: string): string {
  return [...value].map((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint >= 0xe031 && codePoint <= 0xe03a
      ? String(codePoint - 0xe031)
      : character;
  }).join("");
}

function readFirst(root: ParentNode, selectors: string[]): string | null {
  for (const selector of selectors) {
    const element = root.querySelector<HTMLElement>(selector);
    if (element && isVisible(element)) {
      const text = normalize(element.innerText || element.textContent || "");
      if (text) return text;
    }
  }
  return null;
}

function uniqueVisibleElements(elements: HTMLElement[]): HTMLElement[] {
  return [...new Set(elements)].filter(isVisible);
}

function isVisible(element: HTMLElement): boolean {
  return element.getClientRects().length > 0;
}

function extractJobId(url: string): string | null {
  try {
    const match = new URL(url).pathname.match(/\/job_detail\/([^./?]+)/);
    return match?.[1] || null;
  } catch {
    return null;
  }
}

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function normalizeDescription(value: string): string {
  return value
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/[\t ]+/g, " ").trim())
    .filter(Boolean)
    .join("\n")
    .trim();
}

function dedupe(jobs: BossVisibleJob[]): BossVisibleJob[] {
  return [...new Map(jobs.map((job) => [job.external_job_id, job])).values()];
}
