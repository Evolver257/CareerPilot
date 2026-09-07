"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { ThemeToggle } from "./theme-toggle";
import { workspaces, workspaceFor } from "../lib/workspaces";

const groups = [{ label: "求职空间", links: workspaces }];

export function Navigation() {
  const pathname = usePathname();
  const activeLinkRef = useRef<HTMLAnchorElement | null>(null);

  useEffect(() => {
    activeLinkRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [pathname]);

  return (
    <aside className="border-b border-slate-200 bg-white px-5 py-5 lg:min-h-screen lg:w-64 lg:border-b-0 lg:border-r lg:px-6 lg:py-8">
      <div className="flex items-start justify-between gap-3 lg:flex-col">
        <Link className="flex min-w-0 items-center gap-3" href="/dashboard">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-600 font-bold text-white">C</span>
          <span className="min-w-0"><span className="block truncate font-semibold">CareerPilot</span><span className="text-xs text-slate-400">AI job search</span></span>
        </Link>
        <ThemeToggle className="lg:w-full lg:justify-center" />
      </div>
      <nav aria-label="主导航" className="mt-8 flex gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:block lg:space-y-5">
        {groups.map((group) => <div className="flex shrink-0 gap-2 lg:block" key={group.label}>
          <p className="mb-2 hidden px-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 lg:block">{group.label}</p>
          <div className="flex gap-2 lg:block lg:space-y-1">
            {group.links.map((link) => {
              const active = workspaceFor(pathname)?.href === link.href;
              return <Link aria-current={active ? "page" : undefined} key={link.href} ref={active ? activeLinkRef : undefined} className={`block whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium transition ${active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-indigo-50 hover:text-indigo-700"}`} href={link.href}>{link.label}</Link>;
            })}
          </div>
        </div>)}
      </nav>
      <div className="mt-8 hidden rounded-2xl bg-slate-50 p-4 lg:block">
        <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">安全自动化</p>
        <p className="mt-2 text-sm leading-6 text-slate-600">投递前由你确认；遇到登录、验证码或风险提示时自动暂停。</p>
      </div>
    </aside>
  );
}
