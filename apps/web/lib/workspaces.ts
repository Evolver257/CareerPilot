export const workspaces = [
  { href: "/dashboard", label: "工作台", routes: ["/dashboard"], links: [] },
  { href: "/jobs", label: "找职位", routes: ["/jobs", "/ranking", "/browser-tasks"], links: [
    { href: "/jobs", label: "职位库" }, { href: "/ranking", label: "按简历匹配" },
    { href: "/browser-tasks", label: "采集新职位" },
  ] },
  { href: "/campaigns", label: "我的求职", routes: ["/campaigns", "/applications", "/delivery"], links: [
    { href: "/campaigns", label: "投递计划" }, { href: "/applications", label: "投递进度" },
    { href: "/delivery", label: "投递执行与记录" },
  ] },
  { href: "/career-advisor", label: "职业顾问", routes: ["/career-advisor", "/market-insights", "/agent-runs"], links: [
    { href: "/career-advisor", label: "聊职业方向" }, { href: "/market-insights", label: "岗位需求报告" },
    { href: "/agent-runs", label: "生成求职计划" },
  ] },
  { href: "/resume", label: "我的简历", routes: ["/resume"], links: [] },
  { href: "/settings", label: "设置", routes: ["/settings"], links: [] },
];

export function workspaceFor(pathname: string) {
  // An individual automation record belongs to delivery management.
  if (pathname.startsWith("/browser-tasks/")) return workspaces[2];
  return workspaces.find((workspace) => workspace.routes.some((route) => pathname === route || pathname.startsWith(`${route}/`)));
}

export const developerMode = process.env.NEXT_PUBLIC_DEVELOPER_MODE === "true";
