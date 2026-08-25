import Link from "next/link";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "职位探索" },
  { href: "/ranking", label: "智能排名" },
  { href: "/resume", label: "简历管理" },
  { href: "/agent-runs", label: "Agent Trace" },
  { href: "/campaigns", label: "Campaign" },
  { href: "/applications", label: "投递追踪" }
];

export function Navigation() {
  return (
    <aside className="border-b border-slate-200 bg-white px-5 py-5 lg:min-h-screen lg:w-64 lg:border-b-0 lg:border-r lg:px-6 lg:py-8">
      <Link className="flex items-center gap-3" href="/dashboard">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-600 font-bold text-white">C</span>
        <span><span className="block font-semibold">CareerPilot</span><span className="text-xs text-slate-400">AI job search</span></span>
      </Link>
      <nav className="mt-8 flex gap-2 overflow-x-auto lg:block lg:space-y-2">
        {links.map((link) => <Link key={link.href} className="block whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium text-slate-600 transition hover:bg-indigo-50 hover:text-indigo-700" href={link.href}>{link.label}</Link>)}
      </nav>
      <div className="mt-8 hidden rounded-2xl bg-slate-50 p-4 lg:block">
        <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">Phase 7</p>
        <p className="mt-2 text-sm leading-6 text-slate-600">Agent Runtime、Tool Trace 与人工审批已接入。</p>
      </div>
    </aside>
  );
}
