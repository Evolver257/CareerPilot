import type { Job } from "../lib/api";
import { jobDescription, rawJobList, rawJobText, readableJobMarkdown } from "../lib/job-presentation";
import { MarkdownContent } from "./markdown-content";

export function ZhaopinJobDescription({ job }: { job: Job }) {
  const source = rawJobText(job, "description_source");
  const complete = source === "detail_page";
  const companyIntro = rawJobText(job, "company_description");
  const companySummary = rawJobText(job, "company_summary");
  const address = rawJobText(job, "work_address");
  const skills = rawJobList(job, "skills");
  const benefits = rawJobList(job, "benefits");
  return <div className="space-y-6">
    <section className="panel" aria-label="智联职位描述">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">职位描述</h2>
        <span className={`rounded-full px-3 py-1 text-xs font-medium ${complete ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" : "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200"}`}>{complete ? "智联详情页 · 完整 JD" : source === "card_summary" ? "列表摘要 · 待补全" : "已保存 JD · 完整性待核实"}</span>
      </div>
      {!complete && <p className="mt-3 text-sm leading-6 text-amber-800 dark:text-amber-200">这条历史记录尚未确认包含完整职位详情，可使用新版采集重新读取同一岗位。</p>}
      {skills.length > 0 && <div className="mt-4 flex flex-wrap gap-2" aria-label="智联岗位技能标签">{skills.map((skill) => <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" key={skill}>{skill}</span>)}</div>}
      <MarkdownContent className="mt-5 break-words" value={readableJobMarkdown(jobDescription(job))} />
      {benefits.length > 0 && <div className="mt-6 border-t border-slate-100 pt-4 dark:border-slate-800"><h3 className="font-semibold">福利待遇</h3><div className="mt-3 flex flex-wrap gap-2">{benefits.map((benefit) => <span key={benefit} className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-300">{benefit}</span>)}</div></div>}
    </section>
    {(companyIntro || companySummary || address) && <section className="panel" aria-label="智联公司与工作地点">
      <h2 className="text-xl font-semibold">公司与工作地点</h2>
      {companySummary && <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">{companySummary}</p>}
      {address && <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-800">
        <p className="font-medium text-slate-800 dark:text-slate-200">工作地址</p>
        <p className="mt-2 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{address}</p>
        {/[*＊]/.test(address) && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">平台仅公开了部分地址，请在智联原页面确认。</p>}
      </div>}
      {companyIntro && <div className="mt-5"><h3 className="font-medium">公司介绍</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-slate-600 dark:text-slate-300">{companyIntro}</p></div>}
    </section>}
  </div>;
}
