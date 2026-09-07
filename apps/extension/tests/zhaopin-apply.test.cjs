const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { parser, loadTs } = require("./ts-loader.cjs");
const url = "https://www.zhaopin.com/jobdetail/CC123J456.htm?task=test";
const action = { id: "click-one", action: "CLICK", metadata: { expected_job_id: "CC123J456", mode: "zhaopin_immediate_apply" } };
function setup(extra = "", button = '<button id="apply">立即投递</button>', page = url) {
  const { dom } = parser(`<section class="summary-planes"><h1 class="summary-planes__title">算法实习生</h1>${button}</section><div class="describtion-card__detail-content">开发风控系统</div>${extra}`, page);
  const window = dom.window;
  const module = loadTs(path.join(__dirname, "../lib/platforms/zhaopin-apply.ts"), {
    window, document: window.document, getComputedStyle: window.getComputedStyle.bind(window),
    HTMLElement: window.HTMLElement, HTMLAnchorElement: window.HTMLAnchorElement,
    setTimeout: (callback) => queueMicrotask(callback),
  });
  return { dom, window, run: (input = action) => module.executeZhaopinApply(input), button: window.document.querySelector("#apply") };
}
test("clicks the original job once, excludes recommendations, and requires applied confirmation", async () => {
  const fixture = setup('<aside><button>立即投递</button><button>已投递</button></aside>');
  let clicks = 0;
  fixture.button.onclick = () => { clicks++; fixture.button.textContent = "已投递"; };
  const result = await fixture.run();
  assert.equal(result.success, true); assert.equal(result.data.application_status, "submitted");
  assert.equal(result.data.confirmation, "applied_button"); assert.equal(clicks, 1);
  assert.equal((await fixture.run()).data.application_status, "already_applied"); assert.equal(clicks, 1);
  fixture.dom.window.close();
});
test("success toast counts as explicit confirmation", async () => {
  const f = setup();
  f.button.onclick = () => f.window.document.body.insertAdjacentHTML("beforeend", '<div role="alert">投递成功！</div>');
  assert.equal((await f.run()).data.confirmation, "success_notice"); f.dom.window.close();
});
test("real delivery confirmation modal must be visible, never its hidden template", async () => {
  const f = setup('<div class="deliver-greeting-modal" style="display:none"><h3 class="deliver-greeting-modal__title">已向对方发送简历和打招呼语</h3></div>');
  let clicks = 0;
  f.button.onclick = () => { clicks++; f.window.document.querySelector(".deliver-greeting-modal").style.display = "block"; };
  const result = await f.run();
  assert.equal(clicks, 1); assert.equal(result.data.application_status, "submitted"); assert.equal(result.data.confirmation, "success_notice");
  f.dom.window.close();
});
test("offline job cannot be applied to even if a stale button exists", async () => {
  const f = setup('<img class="summary-planes__invalid-text">'); let clicks = 0; f.button.onclick = () => clicks++;
  assert.equal((await f.run()).success, false); assert.equal(clicks, 0); f.dom.window.close();
});
test("click without confirmation pauses and repeated action cannot click again", async () => {
  const f = setup(); let clicks = 0; f.button.onclick = () => clicks++;
  const first = await f.run(); const second = await f.run();
  assert.equal(first.success, false); assert.equal(first.data.application_status, "uncertain");
  assert.equal(second.success, false); assert.equal(clicks, 1);
  f.button.textContent = "已投递";
  assert.equal((await f.run()).success, true); assert.equal(clicks, 1); f.dom.window.close();
});
for (const [html, expected] of [['<div role="dialog">扫码登录</div>', "LOGIN_REQUIRED"], ['<div role="dialog">验证码</div>', "CAPTCHA"], ['<div role="dialog">异常访问</div>', "RISK_CONTROL"], ['<div role="dialog">请选择简历</div>', "UNKNOWN_STATE"]]) {
  test(`pauses before clicking for ${expected}`, async () => {
    const f = setup(html); let clicks = 0; f.button.onclick = () => clicks++;
    const result = await f.run(); assert.equal(result.success, false); assert.equal(result.page_state, expected); assert.equal(clicks, 0); f.dom.window.close();
  });
}
test("resume selection after click requires manual intervention", async () => {
  const f = setup();
  f.button.onclick = () => f.window.document.body.insertAdjacentHTML("beforeend", '<div role="dialog">请选择简历</div>');
  const result = await f.run(); assert.equal(result.success, false); assert.equal(result.page_state, "UNKNOWN_STATE"); f.dom.window.close();
});
for (const button of ['<button id="apply" disabled>立即投递</button>', '<button id="apply" hidden>立即投递</button>', '<button id="apply">立即投递</button><button>立即投递</button>']) {
  test(`rejects unavailable or ambiguous buttons: ${button}`, async () => {
    const f = setup("", button); let clicks = 0; f.button.onclick = () => clicks++;
    const result = await f.run(); assert.equal(result.success, false); assert.equal(clicks, 0); f.dom.window.close();
  });
}
test("wrong job is never clicked; CHECK_STATE itself has no side effects", async () => {
  const f = setup(); let clicks = 0; f.button.onclick = () => clicks++;
  assert.equal((await f.run({ ...action, metadata: { expected_job_id: "CCother" } })).success, false);
  assert.equal((await f.run({ ...action, action: "CHECK_STATE" })).success, true);
  assert.equal(clicks, 0); f.dom.window.close();
});
test("delivery URL whitelist rejects search pages, spoofed domains and credentials", () => {
  const { deliveryPlatform } = loadTs(path.join(__dirname, "../lib/delivery-url.ts"));
  assert.equal(deliveryPlatform(url), "zhaopin");
  assert.equal(deliveryPlatform("https://www.zhipin.com/job_detail/123.html?task=t"), "boss");
  for (const bad of ["https://www.zhaopin.com/sou?kw=AI", "https://www.zhaopin.com.evil.test/jobdetail/CC1.htm", "http://www.zhaopin.com/jobdetail/CC1.htm", "https://user@www.zhaopin.com/jobdetail/CC1.htm", "https://www.zhaopin.com:8080/jobdetail/CC1.htm"]) assert.equal(deliveryPlatform(bad), null);
});
