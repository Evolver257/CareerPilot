import { defineConfig } from "wxt";

export default defineConfig({
  manifest: {
    name: "CareerPilot Browser Agent",
    description: "Executes structured CareerPilot Browser Actions with human control.",
    permissions: ["activeTab", "tabs", "scripting", "storage"],
    host_permissions: ["http://localhost:3000/*", "http://localhost:8010/*", "https://www.zhipin.com/*", "https://zhipin.com/*", "https://m.zhipin.com/*"],
  },
});
