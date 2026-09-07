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
  "li.job-card-box",
  ".job-card-wrap",
  ".job-card-wrapper",
  ".job-card-box",
  ".card-area",
  ".job-card",
  "li[class*='job-card']",
  "[role='listitem'][class*='job']",
  "[data-jobid]",
  "[data-job-id]",
  "[data-encrypt-job-id]",
];
const JOB_LINK_SELECTORS = [
  "a[href*='/job_detail/']",
  "a.job-name",
  "a.job-card-left",
  "a[ka*='search_list_jname']",
  "[data-jobid] a",
  "[data-job-id] a",
];
const TITLE_SELECTORS = [
  ".job-name",
  ".job-title .job-name",
  ".job-info .job-name",
  ".job-title",
  "[data-job-title]",
  "a[href*='/job_detail/']",
  "a[ka*='search_list_jname']",
];
const COMPANY_SELECTORS = [".boss-name", ".company-name", ".company-text", ".company-info", ".brand-name"];
const LOCATION_SELECTORS = [".company-location", ".job-area", ".job-location", ".job-card-location", ".job-address"];
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
const BLOCKER_SCOPE_SELECTORS = [
  "[role='dialog']",
  "[aria-modal='true']",
  "[class*='captcha']",
  "[class*='verify']",
  "[class*='security']",
  "[class*='risk']",
  "[id*='captcha']",
  "[id*='verify']",
  "[id*='security']",
  "[id*='risk']",
  ".geetest_panel",
  ".geetest_holder",
  ".nc-container",
];
const JOB_LIST_SELECTORS = [
  ".job-list-container",
  ".job-list-box",
  ".job-list-wrapper",
  ".job-card-list",
  ".search-job-result",
  ".job-list",
  ".page-jobs-main",
];
export const MAX_BOSS_BATCH_JOBS = 200;
const MIN_SCROLL_ROUNDS = 20;
const MAX_SCROLL_ROUNDS_PER_JOB = 2;
const MAX_STAGNANT_SCROLLS = 8;
const CARD_PACING_MS = 450;
const SCROLL_SETTLE_MS = 600;
const FOREGROUND_NEW_CARD_CHECKS = 16;
const BACKGROUND_NEW_CARD_CHECKS = 12;
const FOREGROUND_NEW_CARD_INTERVAL_MS = 250;
const BACKGROUND_NEW_CARD_INTERVAL_MS = 1_000;
const LIST_VIEWPORT_SCROLL_RATIO = 0.82;
const MIN_CARDS_PER_LIST_SCROLL = 3;
const LIST_BOTTOM_GAP_PX = 24;

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

export function isBossJobSearchUrl(url = window.location.href): boolean {
  try {
    const parsed = new URL(url);
    const pathname = parsed.pathname.replace(/\/+$/, "");
    return BOSS_HOSTS.has(parsed.hostname.toLocaleLowerCase())
      && pathname === "/web/geek/jobs"
      && Boolean(parsed.searchParams.get("query")?.trim());
  } catch {
    return false;
  }
}

export function matchesBossJobSearch(
  url: string,
  requirements: string,
  city: string,
): boolean {
  if (!isBossJobSearchUrl(url)) return false;
  const actual = new URL(url);
  const expected = new URL(buildBossSearchUrl(requirements, city));
  if (actual.searchParams.get("query")?.trim() !== expected.searchParams.get("query")?.trim()) return false;
  const expectedCity = expected.searchParams.get("city");
  return !expectedCity || actual.searchParams.get("city") === expectedCity;
}

export function detectBossPageState(): BossPageState {
  if (!isBossPageUrl()) return "UNKNOWN_STATE";
  const title = normalize(document.title).toLocaleLowerCase();
  const pageText = normalize(document.body.innerText).toLocaleLowerCase();
  const scopedBlockerText = readVisibleBlockerText().toLocaleLowerCase();
  const hasJobSurface = hasVisibleJobSurface();
  // When cards are present, only blocker scopes may override READY. Reading
  // the whole JD here would reintroduce false positives such as a normal job
  // description mentioning "风控" or "安全验证". When no job surface exists,
  // fall back to the full page so standalone login/challenge pages are still
  // classified correctly.
  const content = hasJobSurface
    ? `${title}\n${scopedBlockerText}`
    : `${title}\n${scopedBlockerText}\n${pageText}`;
  if (["验证码", "人机验证", "captcha", "图形验证"].some((marker) => content.includes(marker))) return "CAPTCHA";
  if (["请先登录", "登录后继续", "登录后查看", "登录/注册", "登录注册", "扫码登录", "手机登录", "短信登录", "立即登录", "login required", "sign in"].some((marker) => content.includes(marker))) return "LOGIN_REQUIRED";
  if (["操作频繁", "访问频繁", "platform limit"].some((marker) => content.includes(marker))) return "PLATFORM_LIMIT";
  if (["安全验证", "风险验证", "请完成验证", "拖动滑块", "人机校验", "异常访问", "账号存在风险", "风险提示", "risk control verification", "security verification"].some((marker) => content.includes(marker))) return "RISK_CONTROL";
  if (hasJobSurface) return "READY";
  if (["职位搜索", "职位详情", "立即沟通", "立即投递", "立即网申", "薪资"].some((marker) => pageText.includes(marker))) return "READY";
  return "UNKNOWN_STATE";
}

function readVisibleBlockerText(): string {
  return uniqueVisibleElements(
    BLOCKER_SCOPE_SELECTORS.flatMap((selector) => [...document.querySelectorAll<HTMLElement>(selector)]),
  )
    .map((element) => normalize(element.innerText || element.textContent || ""))
    .filter(Boolean)
    .join("\n");
}

function hasVisibleJobSurface(): boolean {
  const hasCards = discoverJobCards().length > 0;
  const hasDetail = DETAIL_DESCRIPTION_SELECTORS.some((selector) => {
    const element = document.querySelector<HTMLElement>(selector);
    return Boolean(element && isVisible(element));
  });
  return hasCards || hasDetail;
}

export function extractVisibleBossJobs(): BossVisibleJob[] {
  if (!isBossPageUrl()) return [];
  const cards = visibleJobCards();
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

export async function extractVisibleBossJobsWithDetails(
  maxJobs = 20,
  onProgress?: (job: BossVisibleJob, collectedCount: number, targetCount: number) => void | Promise<void>,
  shouldStop?: () => boolean | Promise<boolean>,
): Promise<BossVisibleJob[]> {
  const limit = Math.min(Math.max(maxJobs, 1), MAX_BOSS_BATCH_JOBS);
  const maxScrollRounds = Math.max(MIN_SCROLL_ROUNDS, limit * MAX_SCROLL_ROUNDS_PER_JOB);
  const collected = new Map<string, BossVisibleJob>();
  let stagnantScrolls = 0;

  for (let round = 0; round < maxScrollRounds && collected.size < limit; round += 1) {
    if (await shouldStop?.()) break;
    if (detectBossPageState() !== "READY") break;
    const cards = visibleJobCards();
    if (cards.length === 0) break;

    for (const card of cards) {
      if (await shouldStop?.()) break;
      if (collected.size >= limit) break;
      const job = extractCard(card);
      if (!job || collected.has(job.external_job_id)) continue;

      let enriched = job;
      if (job.description_source !== "detail_panel" && card.isConnected) {
        await paceCardIntoView(card);
        if (await shouldStop?.()) break;
        if (detectBossPageState() !== "READY") break;
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
      await onProgress?.(enriched, collected.size, limit);
      if (await shouldStop?.()) break;
      await wait(CARD_PACING_MS);
    }

    if (await shouldStop?.()) break;
    if (collected.size >= limit || detectBossPageState() !== "READY") break;
    const knownJobIds = new Set(collected.keys());
    const scrollTarget = findJobListScrollTarget(cards);
    await scrollJobList(scrollTarget, cards);
    const foundNewCards = await waitForNewJobCards(knownJobIds);
    if (foundNewCards) {
      stagnantScrolls = 0;
    } else if (hasReachedJobListEnd()) {
      break;
    } else {
      stagnantScrolls += 1;
      if (stagnantScrolls >= MAX_STAGNANT_SCROLLS) break;
    }
  }

  return [...collected.values()].slice(0, limit);
}

function extractCard(card: HTMLElement): BossVisibleJob | null {
  const link = findJobLink(card);
  const jobUrl = link?.href || window.location.href;
  const externalJobId = readJobId(card, link, jobUrl);
  const title = readFirst(card, TITLE_SELECTORS)
    || normalize(link?.getAttribute("title") || link?.getAttribute("aria-label") || link?.textContent || "");
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
  return discoverJobCards();
}

function discoverJobCards(): HTMLElement[] {
  const candidates = CARD_SELECTORS.flatMap((selector) => [
    ...document.querySelectorAll<HTMLElement>(selector),
  ]);
  for (const selector of JOB_LINK_SELECTORS) {
    for (const link of document.querySelectorAll<HTMLElement>(selector)) {
      const card = link.closest<HTMLElement>(
        "li.job-card-box, li.job-card-wrapper, .job-card-wrap, .job-card-wrapper, .job-card-box, .job-card, [data-jobid], [data-job-id], [data-encrypt-job-id], li, [role='listitem']",
      );
      candidates.push(card ?? link);
    }
  }
  return uniqueVisibleElements(candidates).filter((candidate) => {
    if (findJobLink(candidate)) return true;
    return Boolean(readJobId(candidate, null, window.location.href) && readFirst(candidate, TITLE_SELECTORS));
  });
}

function findJobLink(card: HTMLElement): HTMLAnchorElement | null {
  if (card instanceof HTMLAnchorElement && isJobLink(card)) return card;
  for (const selector of JOB_LINK_SELECTORS) {
    const link = card.querySelector<HTMLAnchorElement>(selector);
    if (link) return link;
  }
  return null;
}

function isJobLink(link: HTMLAnchorElement): boolean {
  return link.pathname.includes("/job_detail/")
    || link.classList.contains("job-name")
    || (link.getAttribute("ka") || "").includes("search_list_jname");
}

function readJobId(card: HTMLElement, link: HTMLAnchorElement | null, jobUrl: string): string | null {
  const sources = [card, link, link?.closest<HTMLElement>("[data-jobid], [data-job-id], [data-encrypt-job-id]")];
  for (const source of sources) {
    if (!source) continue;
    const value = source.dataset.jobid
      || source.dataset.jobId
      || source.dataset.encryptJobId
      || source.getAttribute("data-jobid")
      || source.getAttribute("data-job-id")
      || source.getAttribute("data-encrypt-job-id");
    if (value) return value;
  }
  return extractJobId(jobUrl);
}

export function describeBossJobSurface(): string {
  const linkCount = JOB_LINK_SELECTORS.reduce(
    (count, selector) => count + document.querySelectorAll(selector).length,
    0,
  );
  const cards = discoverJobCards();
  const parsedCount = cards.filter((card) => extractCard(card) !== null).length;
  const noResult = ["暂无相关职位", "没有找到相关职位", "暂无职位", "无搜索结果"].some(
    (marker) => document.body.innerText.replace(/\s+/g, "").includes(marker),
  );
  return [
    `state=${detectBossPageState()}`,
    `ready=${document.readyState}`,
    `links=${linkCount}`,
    `cards=${cards.length}`,
    `parsed=${parsedCount}`,
    `empty=${noResult}`,
    `path=${window.location.pathname}`,
  ].join(", ");
}

function findJobListScrollTarget(cards: HTMLElement[]): HTMLElement | null {
  let ancestor = cards[0]?.parentElement ?? null;
  while (ancestor && ancestor !== document.body && ancestor !== document.documentElement) {
    if (isScrollable(ancestor)) return ancestor;
    ancestor = ancestor.parentElement;
  }

  for (const selector of JOB_LIST_SELECTORS) {
    const candidate = document.querySelector<HTMLElement>(selector);
    if (candidate && isScrollable(candidate)) return candidate;
  }

  for (const selector of JOB_LIST_SELECTORS) {
    const candidate = document.querySelector<HTMLElement>(selector);
    if (candidate && isScrollContainer(candidate)) return candidate;
  }

  ancestor = cards[0]?.parentElement ?? null;
  while (ancestor && ancestor !== document.body && ancestor !== document.documentElement) {
    if (isScrollContainer(ancestor)) return ancestor;
    ancestor = ancestor.parentElement;
  }

  const scrollingElement = document.scrollingElement;
  return scrollingElement instanceof HTMLElement ? scrollingElement : document.documentElement;
}

function isScrollable(element: HTMLElement): boolean {
  if (!isScrollContainer(element)) return false;
  return element.scrollHeight > element.clientHeight + 8;
}

function isScrollContainer(element: HTMLElement): boolean {
  if (element.clientHeight <= 0) return false;
  const overflowY = window.getComputedStyle(element).overflowY;
  return ["auto", "scroll", "overlay"].includes(overflowY);
}

async function scrollJobList(target: HTMLElement | null, cards: HTMLElement[]): Promise<void> {
  if (!target) return;
  const cardHeight = Math.round(cards[0]?.getBoundingClientRect().height ?? 180);
  const viewportHeight = getScrollViewportHeight(target);
  const distance = Math.max(
    cardHeight * MIN_CARDS_PER_LIST_SCROLL,
    Math.round(viewportHeight * LIST_VIEWPORT_SCROLL_RATIO),
  );
  const maxTop = Math.max(0, target.scrollHeight - viewportHeight);
  const nextTop = Math.min(
    maxTop,
    Math.max(target.scrollTop + distance, maxTop - LIST_BOTTOM_GAP_PX),
  );

  setScrollTopImmediately(target, nextTop);
  notifyListScrolled(target);
  await wait(document.hidden ? BACKGROUND_NEW_CARD_INTERVAL_MS : SCROLL_SETTLE_MS);

  const lastCard = cards.at(-1);
  if (lastCard?.isConnected) {
    lastCard.scrollIntoView({ block: "end", inline: "nearest", behavior: "auto" });
  }

  // BOSS loads the next batch only when the list reaches its current bottom.
  // Recalculate synchronously so hidden tabs do not depend on animation frames.
  const refreshedViewportHeight = getScrollViewportHeight(target);
  const refreshedMaxTop = Math.max(0, target.scrollHeight - refreshedViewportHeight);
  setScrollTopImmediately(target, refreshedMaxTop);
  void target.getBoundingClientRect().height;
  notifyListScrolled(target);
  await wait(document.hidden ? BACKGROUND_NEW_CARD_INTERVAL_MS : SCROLL_SETTLE_MS);
}

function setScrollTopImmediately(target: HTMLElement, top: number): void {
  const normalizedTop = Math.max(0, Math.round(top));
  if (
    target === document.scrollingElement
    || target === document.documentElement
    || target === document.body
  ) {
    window.scrollTo({ top: normalizedTop, behavior: "auto" });
  }
  target.scrollTop = normalizedTop;
}

function notifyListScrolled(target: HTMLElement): void {
  target.dispatchEvent(new Event("scroll", { bubbles: true }));
  if (target === document.scrollingElement || target === document.documentElement || target === document.body) {
    window.dispatchEvent(new Event("scroll"));
  }
}

function getScrollViewportHeight(target: HTMLElement): number {
  if (
    target === document.scrollingElement
    || target === document.documentElement
    || target === document.body
  ) {
    return Math.max(1, window.innerHeight);
  }
  return Math.max(1, target.clientHeight);
}

async function paceCardIntoView(card: HTMLElement): Promise<void> {
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  await wait(CARD_PACING_MS);
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function waitForNewJobCards(knownJobIds: Set<string>): Promise<boolean> {
  const background = document.hidden;
  const checks = background ? BACKGROUND_NEW_CARD_CHECKS : FOREGROUND_NEW_CARD_CHECKS;
  const interval = background ? BACKGROUND_NEW_CARD_INTERVAL_MS : FOREGROUND_NEW_CARD_INTERVAL_MS;
  for (let check = 0; check < checks; check += 1) {
    await wait(interval);
    if (detectBossPageState() !== "READY") return false;
    const hasNewCard = visibleJobCards().some((card) => {
      const job = extractCard(card);
      return Boolean(job && !knownJobIds.has(job.external_job_id));
    });
    if (hasNewCard) return true;

    // Hidden tabs may defer BOSS' observer callback. Reassert the real list bottom
    // periodically without relying on requestAnimationFrame or smooth scrolling.
    if (background && check > 0 && check % 3 === 0) {
      const cards = visibleJobCards();
      const target = findJobListScrollTarget(cards);
      if (target) {
        const viewportHeight = getScrollViewportHeight(target);
        setScrollTopImmediately(target, Math.max(0, target.scrollHeight - viewportHeight));
        void target.getBoundingClientRect().height;
        notifyListScrolled(target);
      }
    }
  }
  return false;
}

function hasReachedJobListEnd(): boolean {
  const pageText = document.body.innerText.replace(/\s+/g, "");
  if (["没有更多职位", "没有更多了", "已加载全部", "到底了"].some((marker) => pageText.includes(marker))) {
    return true;
  }
  return false;
}

async function waitForJobDetail(title: string, card: HTMLElement): Promise<string | null> {
  const expectedTitle = normalize(title).toLocaleLowerCase();
  const startedAt = Date.now();
  while (Date.now() - startedAt < 2500) {
    await wait(150);
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
