# BOSS 直聘 Adapter

CareerPilot supports a safe BOSS 直聘 compatibility path through the existing `JobPlatformAdapter` boundary.

## Supported flow

1. On `/browser-tasks`, the user enters job requirements, city, and a visible-result limit. The page-to-extension bridge verifies that the local CareerPilot extension is present.
2. The extension opens the official BOSS search page in the user's browser. If necessary, the user logs in or completes verification manually.
3. The extension walks the currently visible result cards one at a time, switches the official right-hand detail panel, and captures the full visible JD. When the requested amount exceeds the current card batch, it scrolls the left result list, waits for lazy-loaded cards, deduplicates them, and continues until the requested limit is reached or the list stops producing new jobs. A card summary is retained only when a detail panel cannot be confirmed.
4. The CareerPilot page sends those structured fields to `POST /api/platforms/boss/import-visible`. The API validates `zhipin.com` URLs, normalizes the JD, deduplicates by platform/external ID or content hash, and persists the job. Recollecting a previously summarized job with a full detail-panel JD upgrades the existing database record in place.
   Salary text is decoded at both the extension and API boundaries because BOSS may render digits through the `kanzhun-mix` private-use font. Existing encoded BOSS salary records are normalized by migration `0008_decode_boss_salary`.
5. The user selects exact imported jobs and a resume. `POST /api/campaigns/curated` creates an auditable `WAITING_APPROVAL` candidate set; the explicit page confirmation advances the selected Applications to `QUEUED`.
6. The page creates one BOSS BrowserTask per approved Application and asks the extension to open only the backend-generated task URL. The extension checks page state before the approved application action. Results are recorded in Application and BrowserTask history.

## Safety boundary

The adapter does not make HTTP requests to BOSS, use undocumented APIs, upload cookies/passwords/tokens, upload raw HTML, or run unattended page crawling. It only captures the current visible page through the extension. CAPTCHA, login prompts, platform limits, risk control, DOM changes, and unknown states pause the task as `REQUEST_USER_ACTION`.

BOSS's official user agreement warns against unauthorized acquisition of platform information using spider/crawler/imitative programs and against bypassing platform processes or limits. Review the [official BOSS user agreement](https://www.zhipin.com/web/common/protocol/protocol-2019-09-30.html) and use the adapter only within an authorized, user-controlled session.

## Key interfaces

- `POST /api/platforms/boss/import-visible` — import structured fields from the currently visible page.
- `POST /api/campaigns/curated` — create an exact user-selected candidate set without rerunning broad discovery.
- `GET /api/browser-tasks/platforms` — shows `boss` as `user_browser_session` and `safe_for_automation: false`.
- `POST /api/browser-tasks` with `platform: "boss"` — create a user-confirmed application task for an approved Application.
- `/browser-tasks` page bridge — send structured search requirements and launch approved task URLs.
- Extension popup — retain manual visible-page capture as a fallback.
- `/jobs/{id}` — display the persisted local job and full JD, with an optional link back to the official BOSS page.

Selectors, parser, detector, actions, and adapter implementation live under `services/api/app/platforms/boss/` and the matching extension parser under `apps/extension/lib/platforms/boss.ts`. This keeps BOSS DOM assumptions out of Campaign, Ranking, and Agent Runtime services.

## Known limitations

- BOSS DOM selectors can change; unknown page structures fail closed and require a user review.
- The extension currently supports both the legacy job-card layout and the `/web/geek/jobs` split-pane layout (`job-card-wrap`, `job-card-box`, `boss-name`, `company-location`, and `job-detail-box`). Collection retries while the visible list is rendering asynchronously and marks every saved item as either `detail_panel` or `card_summary`.
- A single request can collect up to 50 user-visible jobs. The actual total still depends on cards that BOSS makes available while the left result list is scrolled.
- The current implementation imports visible structured cards, not a server-side search crawler.
- “一键投递” means one explicit approval for the checked job set. Each job still receives its own traceable BrowserTask and stops independently on login, CAPTCHA, risk control, platform limits, DOM changes, or unknown states.
