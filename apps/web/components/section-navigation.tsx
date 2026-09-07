"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { workspaceFor } from "../lib/workspaces";

export function SectionNavigation() {
  const pathname = usePathname();
  const workspace = workspaceFor(pathname);
  if (!workspace?.links.length) return null;
  return <nav aria-label={`${workspace.label}功能`} className="section-navigation mx-auto mb-6 flex w-full max-w-7xl gap-2 overflow-x-auto border-b border-[var(--cp-border)] pb-3">
    {workspace.links.map((link) => {
      const active = pathname === link.href || pathname.startsWith(`${link.href}/`) || (link.href === "/delivery" && pathname.startsWith("/browser-tasks/"));
      return <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} className={`shrink-0 rounded-lg px-3 py-2 text-sm font-medium transition-colors motion-reduce:transition-none ${active ? "bg-[var(--cp-accent-surface)] text-[var(--cp-accent-text)]" : "text-[var(--cp-text-muted)] hover:bg-[var(--cp-surface-subtle)]"}`}>{link.label}</Link>;
    })}
  </nav>;
}
