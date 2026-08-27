"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "./theme-toggle";

const links = [
  { href: "/dashboard", label: "工作台" },
  { href: "/jobs", label: "找职位" },
  { href: "/ranking", label: "智能匹配" },
  { href: "/resume", label: "我的简历" },
  { href: "/agent-runs", label: "求职 Agent" },
  { href: "/campaigns", label: "投递计划" },
  { href: "/applications", label: "投递进度" },
  { href: "/browser-tasks", label: "自动化任务" },
  { href: "/settings", label: "LLM 设置" },
];

export function Navigation() {
  const pathname = usePathname();

  return (
    <aside className="border-b border-slate-200 bg-white px-5 py-5 lg:min-h-screen lg:w-64 lg:border-b-0 lg:border-r lg:px-6 lg:py-8">
      <div className="flex items-start justify-between gap-3 lg:flex-col">
        <Link className="flex min-w-0 items-center gap-3" href="/dashboard">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-600 font-bold text-white">C</span>
          <span className="min-w-0"><span className="block truncate font-semibold">CareerPilot</span><span className="text-xs text-slate-400">AI job search</span></span>
        </Link>
        <ThemeToggle className="lg:w-full lg:justify-center" />
      </div>
      <nav className="mt-8 flex gap-2 overflow-x-auto lg:block lg:space-y-2">
        {links.map((link) => {
          const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
          return <Link aria-current={active ? "page" : undefined} key={link.href} className={`block whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium transition ${active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-indigo-50 hover:text-indigo-700"}`} href={link.href}>{link.label}</Link>;
        })}
      </nav>
      <div className="mt-8 hidden rounded-2xl bg-slate-50 p-4 lg:block">
        <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">安全自动化</p>
        <p className="mt-2 text-sm leading-6 text-slate-600">投递前由你确认；遇到登录、验证码或风险提示时自动暂停。</p>
      </div>
    </aside>
  );
}
