import type { Metadata } from "next";

import "./globals.css";
import { Navigation } from "../components/navigation";

export const metadata: Metadata = {
  title: "CareerPilot",
  description: "AI-assisted job search foundation"
};

const themeScript = `(() => {
  try {
    const storedTheme = window.localStorage.getItem("careerpilot-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (storedTheme === "dark" || (!storedTheme && prefersDark)) {
      document.documentElement.classList.add("dark");
    }
  } catch {}
})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <div className="min-h-screen lg:flex">
          <Navigation />
          <main className="min-w-0 flex-1 p-5 sm:p-8 lg:p-10">{children}</main>
        </div>
      </body>
    </html>
  );
}
