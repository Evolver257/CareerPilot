import type { Metadata } from "next";

import "./globals.css";
import { Navigation } from "../components/navigation";

export const metadata: Metadata = {
  title: "CareerPilot",
  description: "AI-assisted job search foundation"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="min-h-screen lg:flex">
          <Navigation />
          <main className="flex-1 p-5 sm:p-8 lg:p-10">{children}</main>
        </div>
      </body>
    </html>
  );
}
