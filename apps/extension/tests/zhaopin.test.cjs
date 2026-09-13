const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { parser, loadTs } = require("./ts-loader.cjs");
const url = "https://www.zhaopin.com/sou?jl=530&kw=AI";
const detailUrl = (id) => "https://www.zhaopin.com/jobdetail/" + id + ".htm";
const cardHtml = (id) => '<div class="joblist-box__item"><a href="/companydetail/CZ123.htm">错误公司链接</a><a class="jobinfo__name" href="' + detailUrl(id) + '">算法实习生</a><p class="jobinfo__salary">200-300元/天</p><div class="jobinfo__other-info-item">北京·海淀</div><div class="jobinfo__other-info-item">经验不限</div><div class="jobinfo__other-info-item">硕士</div><a class="companyinfo__name">示例公司</a></div>';
const detailHtml = '<h1 class="summary-planes__title">算法实习生</h1><span class="summary-planes__salary">**-**元</span><ul class="summary-planes__info"><li>北京 海淀</li><li>经验不限</li><li>硕士</li></ul><div class="describtion-card__detail-content">工作职责<br>1. 开发风控系统及验证码识别测试。<br>任职要求<br>1. 熟悉 Python。<br>2. 熟悉 RAG。</div><span class="describtion-card__skills-item">Python</span><a class="company-info__name">示例公司</a><div class="company-info__intro">公司介绍不要混入 JD</div>';

test("real class names: select job link, HTTPS normalization, and card metadata", () => {
  const { module, dom } = parser(cardHtml("CC123J456").replace('href="' + detailUrl("CC123J456"), 'href="http://www.zhaopin.com/jobdetail/CC123J456.htm'), url);
  const jobs = module.extractVisibleZhaopinJobs();
  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].external_job_id, "CC123J456");
  assert.equal(jobs[0].job_url, detailUrl("CC123J456"));
  assert.equal(jobs[0].education, "硕士");
  assert.equal(jobs[0].description, "算法实习生");
  dom.window.close();
});
test("full JD excludes recommendations/company intro; preserves line breaks and avoids risk false positives", () => {
  const { module, dom } = parser(detailHtml + cardHtml("CCother"), detailUrl("CC123J456"));
  assert.equal(module.detectZhaopinPageState(), "READY");
  const jobs = module.extractVisibleZhaopinJobs();
  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].external_job_id, "CC123J456");
  assert.ok(jobs[0].description.includes("\n任职要求\n"));
  assert.ok(!jobs[0].description.includes("公司介绍"));
  assert.equal(jobs[0].requirements.length, 2);
  dom.window.document.querySelector(".describtion-card__detail-content").innerHTML = "岗位基本需求<br>1. 熟悉 Python<br>2. 熟悉 RAG";
  assert.equal(module.extractZhaopinDetail().requirements.length, 2);
  assert.equal(jobs[0].salary_text, null);
  assert.equal(module.extractZhaopinDetail("CCother"), null);
  const merged = module.mergeZhaopinDetail({ ...jobs[0], salary_text: "200-300元/天" }, jobs[0]);
  assert.equal(merged.salary_text, "200-300元/天");
  assert.equal(merged.raw_data.salary_source, "search_card");
  assert.throws(() => module.mergeZhaopinDetail({ ...jobs[0], external_job_id: "other" }, jobs[0]));
  dom.window.close();
});
test("visible verification pauses while hidden dialogs and header login links do not", () => {
  const { module, dom } = parser(detailHtml + '<a>登录/注册</a><div role="dialog" style="display:none">扫码登录</div>', detailUrl("CC123"));
  assert.equal(module.detectZhaopinPageState(), "READY");
  dom.window.document.querySelector("[role=dialog]").style.display = "block";
  assert.equal(module.detectZhaopinPageState(), "LOGIN_REQUIRED");
  dom.window.close();
});
test("hidden recruitment tabs are paused instead of being scraped", () => {
  const { module, dom } = parser(detailHtml, detailUrl("CC123"));
  Object.defineProperty(dom.window.document, "hidden", { configurable: true, value: true });
  assert.equal(module.detectZhaopinPageState(), "TAB_HIDDEN");
  dom.window.close();
});

function harness(count = 20, existing) {
  let stored = existing ? structuredClone(existing) : null;
  let captcha = false, gate = null, failImport = false;
  const tabs = new Map();
  const imported = [], scored = [];
  let nextTab = 1;
  const job = (id, detail = false) => ({
    external_job_id: String(id), title: "岗位" + id, description: detail ? "职责\n任职要求：Python RAG" : "摘要",
    job_url: detailUrl(id), location: "北京", company_name: "公司", salary_text: "10-20K",
    education: "本科", experience: "经验不限", requirements: [], skills: ["Python"], benefits: [],
    raw_data: { description_source: detail ? "detail_page" : "card_summary" },
  });
  const globals = {
    setTimeout: (fn) => setTimeout(fn, 0),
    browser: {
      storage: { local: { get: async () => ({ careerpilot_zhaopin_background_search: structuredClone(stored) }), set: async (value) => { stored = structuredClone(value.careerpilot_zhaopin_background_search); } } },
      tabs: {
        create: async ({ url, active }) => { assert.equal(active, true); const tab = { id: nextTab++, url, status: "complete" }; tabs.set(tab.id, tab); return tab; },
        get: async (id) => { if (!tabs.has(id)) throw new Error("tab missing"); return tabs.get(id); },
        update: async (id, value) => { Object.assign(tabs.get(id), value); return tabs.get(id); },
        sendMessage: async (id, message) => {
          const tab = tabs.get(id);
          if (message.type === "ADVANCE_ZHAOPIN_SEARCH") return { advanced: true, next_url: url + "&p=2" };
          const match = tab.url.match(/jobdetail\/(\d+)\.htm/);
          if (match && captcha) return { success: false, jobs: [], page_url: tab.url, page_state: "CAPTCHA", error: "需要验证码" };
          const items = match ? [job(match[1], true)] : Array.from({ length: tab.url.includes("p=2") ? 5 : Math.min(count, 15) }, (_, i) => job(tab.url.includes("p=2") ? i + 16 : i + 1));
          return { success: true, jobs: items, page_url: tab.url, page_state: "READY" };
        },
      },
    },
    fetch: async (endpoint, options) => {
      const body = JSON.parse(options.body);
      if (endpoint.includes("quick-score")) {
        scored.push(body.job_ids[0]); return { ok: true, json: async () => ({ items: [{ score: 60 }] }) };
      }
      if (gate) await gate;
      if (failImport) return { ok: false, status: 500 };
      imported.push(body.jobs[0]);
      return { ok: true, json: async () => ({ items: [{ id: body.jobs[0].external_job_id }], created: 1, updated: 0 }) };
    },
  };
  let runtime = loadTs(path.join(__dirname, "../lib/zhaopin-collection.ts"), globals);
  const send = (type, extra = {}) => runtime.handleZhaopinCollection({ source: "careerpilot-web", type, request_id: "run", ...extra });
  return {
    send, get task() { return stored; }, imported, scored, tabs,
    start: () => send("ZHAOPIN_SEARCH_REQUEST", { payload: { search_url: url, max_jobs: count, resume_id: "resume", quick_score_threshold: 50 } }),
    captcha: (value) => { captcha = value; },
    gate: (value) => { gate = value; },
    fail: (value) => { failImport = value; },
    restart: () => { runtime = loadTs(path.join(__dirname, "../lib/zhaopin-collection.ts"), globals); },
  };
}
async function until(predicate) {
  for (let i = 0; i < 2000; i++) { if (predicate()) { await new Promise((r) => setTimeout(r, 2)); return; } await new Promise((r) => setTimeout(r, 2)); }
  throw new Error("condition timeout");
}
test("cross-page 20 jobs: incremental full JD persistence, quick scores, one reused detail tab", async () => {
  const h = harness();
  await h.start(); await until(() => h.task?.status === "COMPLETED");
  assert.equal(h.task.jobs.length, 20);
  assert.equal(h.imported.length, 20); assert.equal(h.scored.length, 20);
  assert.equal(h.tabs.size, 2);
  assert.equal(new Set(h.imported.map((j) => j.external_job_id)).size, 20);
  assert.ok(h.imported.every((j) => j.raw_data.description_source === "detail_page"));
});
test("cancel during import keeps persisted result and cannot be overwritten by completion", async () => {
  const h = harness(3);
  let release; h.gate(new Promise((resolve) => { release = resolve; }));
  await h.start(); await until(() => h.task?.detail_tab_id !== undefined);
  await h.send("ZHAOPIN_SEARCH_CANCEL_REQUEST"); release();
  await until(() => h.task?.jobs.length === 1);
  assert.equal(h.task.status, "CANCELLED");
  assert.equal(h.imported.length, 1); assert.equal(h.scored.length, 0);
});
test("verification and persistence failures preserve queue for resume", async () => {
  const h = harness(2); h.captcha(true);
  await h.start(); await until(() => h.task?.status === "WAITING_FOR_USER");
  assert.equal(h.task.pending.length, 2); assert.equal(h.imported.length, 0);
  h.captcha(false); h.fail(true);
  await h.send("ZHAOPIN_SEARCH_RESUME_REQUEST"); await until(() => h.task?.status === "FAILED");
  assert.equal(h.task.pending.length, 2);
  h.fail(false); await h.send("ZHAOPIN_SEARCH_RESUME_REQUEST"); await until(() => h.task?.status === "COMPLETED");
  assert.equal(h.imported.length, 2);
});
test("service-worker restart exposes interrupted state and resumes stored pending jobs", async () => {
  const h = harness(1, { request_id: "run", status: "RUNNING", search_url: url, page_url: url, target_count: 1,
    jobs: [], pending: [], created_count: 0, updated_count: 0, quick_score_threshold: 50, page_state: "READY",
    started_at: new Date().toISOString(), updated_at: new Date().toISOString() });
  const result = await h.send("ZHAOPIN_SEARCH_STATUS_REQUEST");
  assert.equal(result.task.status, "INTERRUPTED");
  await h.send("ZHAOPIN_SEARCH_RESUME_REQUEST"); await until(() => h.task?.status === "COMPLETED");
  assert.equal(h.imported.length, 1);
});
