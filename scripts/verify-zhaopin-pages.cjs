// Read-only verification against two public pages; never imports jobs into the user's database.
const assert = require("node:assert/strict");
const { parser } = require("../apps/extension/tests/ts-loader.cjs");
async function main() {
  const searchUrl = "https://www.zhaopin.com/sou?jl=530&kw=AI%20Agent";
  const searchResponse = await fetch(searchUrl, { signal: AbortSignal.timeout(25_000) });
  assert.ok(searchResponse.ok);
  const search = parser(await searchResponse.text(), searchResponse.url);
  const jobs = search.module.extractVisibleZhaopinJobs();
  assert.ok(jobs.length > 0, "public search must expose job cards");
  assert.equal(search.module.detectZhaopinPageState(), "READY");
  const candidate = jobs[0];
  console.log(JSON.stringify({ page: "search", title: search.dom.window.document.title, cards: jobs.length,
    first_job: candidate.title, source: candidate.job_url, company: candidate.company_name,
    salary: candidate.salary_text, education: candidate.education, experience: candidate.experience }));
  const detailResponse = await fetch(candidate.job_url, { signal: AbortSignal.timeout(25_000) });
  assert.ok(detailResponse.ok);
  const detail = parser(await detailResponse.text(), detailResponse.url);
  const full = detail.module.extractZhaopinDetail(candidate.external_job_id);
  assert.ok(full, "actual detail must match the requested job");
  assert.ok(full.description.length > 50, "full JD must contain more than a title");
  const merged = detail.module.mergeZhaopinDetail(candidate, full);
  console.log(JSON.stringify({ page: "detail", title: full.title, state: detail.module.detectZhaopinPageState(),
    description_length: full.description.length, paragraphs: full.description.split("\n").length,
    headings: full.description.split("\n").filter((line) => /要求|需求|资格/.test(line) && line.length < 30),
    requirements: full.requirements.length, skills: full.skills, company: full.company_name,
    education: full.education, experience: full.experience, salary: merged.salary_text,
    salary_source: merged.raw_data.salary_source, description_source: full.raw_data.description_source }));
  search.dom.window.close(); detail.dom.window.close();
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
