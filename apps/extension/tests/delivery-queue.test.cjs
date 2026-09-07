const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs, parser } = require("./ts-loader.cjs");

test("mixed platform queue reuses one tab, deduplicates and pauses until task completion", async () => {
  let onMessage, onUpdated;
  const creates = [], updates = [], sockets = [], timers = [];
  let tab; let failCreate = true;
  class Socket {
    constructor() { this.handlers = {}; sockets.push(this); }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    send() {}
    close() { this.handlers.close?.(); }
    async emit(data) { await this.handlers.message({ data: JSON.stringify(data) }); }
  }
  const browser = {
    runtime: { onMessage: { addListener: (fn) => { onMessage = fn; } } },
    tabs: {
      onUpdated: { addListener: (fn) => { onUpdated = fn; } },
      create: async (args) => { if (failCreate) { failCreate = false; throw new Error("temporary tab failure"); } creates.push(args); tab = { id: 9, status: "complete", ...args }; return tab; },
      get: async () => tab,
      update: async (id, args) => { updates.push({ id, ...args }); tab = { ...tab, ...args }; return tab; },
      sendMessage: async () => ({}),
    },
  };
  loadTs(path.join(__dirname, "../entrypoints/background.ts"), { browser, WebSocket: Socket, defineBackground: (fn) => fn(), setTimeout: (fn) => timers.push(fn) });
  const request = { source: "careerpilot-web", type: "RECRUITMENT_TASK_BATCH_LAUNCH_REQUEST", request_id: "request", tasks: [
    { task_id: "one", platform: "boss", url: "https://www.zhipin.com/job_detail/one.html?task=one" },
    { task_id: "two", platform: "zhaopin", url: "https://www.zhaopin.com/jobdetail/CCtwo.htm?task=two" },
  ] };
  assert.equal((await onMessage(request, {})).success, false);
  assert.equal((await onMessage(request, {})).success, true);
  assert.equal((await onMessage(request, {})).accepted_count, 0);
  assert.equal(creates.length, 1); assert.equal(creates[0].active, false);
  await onUpdated(9, { status: "complete" }, tab);
  await sockets[0].emit({ type: "REQUEST_USER_ACTION", task_id: "one", action: { id: "pause", action: "REQUEST_USER_ACTION" } });
  assert.equal(timers.length, 0); assert.equal(updates.length, 0);
  await sockets[0].emit({ type: "TASK_COMPLETED", task_id: "one" });
  timers.shift()(); await new Promise((resolve) => setImmediate(resolve));
  assert.equal(creates.length, 1); assert.equal(updates.length, 1); assert.equal(updates[0].id, 9);
  assert.equal(updates[0].url, request.tasks[1].url);
});

test("human action notice never sends an ACTION_RESULT back to a paused server", async () => {
  const { dom } = parser("<h1>岗位详情</h1>", "https://www.zhaopin.com/jobdetail/CC123.htm");
  let listener; const sent = [];
  loadTs(path.join(__dirname, "../entrypoints/content.ts"), {
    window: dom.window, document: dom.window.document,
    defineContentScript: (definition) => definition.main(),
    browser: { runtime: { onMessage: { addListener: (fn) => { listener = fn; } }, sendMessage: async (message) => sent.push(message) } },
  });
  await listener({ type: "REQUEST_USER_ACTION", action: { id: "pause", action: "REQUEST_USER_ACTION", metadata: { reason: "请完成登录" } } });
  assert.equal(sent.length, 0); dom.window.close();
});

test("BOSS immediate online application is marked for manual delivery without clicking", async () => {
  const { dom } = parser(
    '<button id="apply">立即网申</button>',
    "https://www.zhipin.com/job_detail/manual-1.html?task=manual-1",
  );
  const window = dom.window;
  window.HTMLElement.prototype.getClientRects = () => [{ width: 120, height: 40 }];
  Object.defineProperty(window.document.body, "innerText", { value: "立即网申", configurable: true });
  let listener;
  loadTs(path.join(__dirname, "../entrypoints/content.ts"), {
    window,
    document: window.document,
    HTMLElement: window.HTMLElement,
    HTMLInputElement: window.HTMLInputElement,
    HTMLTextAreaElement: window.HTMLTextAreaElement,
    getComputedStyle: window.getComputedStyle.bind(window),
    defineContentScript: (definition) => definition.main(),
    browser: {
      runtime: {
        onMessage: { addListener: (fn) => { listener = fn; } },
        sendMessage: async () => undefined,
      },
    },
  });
  const button = window.document.querySelector("#apply");
  let clicks = 0;
  button.onclick = () => { clicks += 1; };
  const result = await listener({
    type: "ACTION",
    action: {
      id: "manual-apply",
      action: "CLICK",
      target: { strategy: "boss-semantic", name: "立即沟通" },
      metadata: { mode: "boss_immediate_communication" },
    },
  });
  assert.equal(result.success, false);
  assert.equal(result.page_state, "READY");
  assert.equal(result.data.application_status, "MANUAL_REQUIRED");
  assert.equal(result.data.boss_action, "manual_apply_required");
  assert.equal(clicks, 0);
  dom.window.close();
});
