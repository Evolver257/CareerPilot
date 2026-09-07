const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("../../web/node_modules/typescript");
const { JSDOM } = require("../../web/node_modules/jsdom");

function loadTs(file, globals = {}, cache = new Map()) {
  file = path.resolve(file);
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} };
  cache.set(file, module);
  const code = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, {
    module, exports: module.exports, URL, AbortSignal, setTimeout, clearTimeout, console,
    require: (id) => id.startsWith(".") ? loadTs(path.resolve(path.dirname(file), id + ".ts"), globals, cache) : require(id),
    ...globals,
  }, { filename: file });
  return module.exports;
}
function parser(html, url) {
  const dom = new JSDOM(html, { url });
  const window = dom.window;
  window.HTMLElement.prototype.getBoundingClientRect = () => ({ height: 40, width: 100 });
  window.HTMLElement.prototype.scrollIntoView = () => {};
  return { dom, module: loadTs(path.join(__dirname, "../lib/platforms/zhaopin.ts"), {
    window, document: window.document, getComputedStyle: window.getComputedStyle.bind(window),
    HTMLElement: window.HTMLElement, HTMLAnchorElement: window.HTMLAnchorElement,
  }) };
}
module.exports = { loadTs, parser };
