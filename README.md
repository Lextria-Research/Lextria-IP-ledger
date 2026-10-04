# Lextria IP Ledger

A single-page dashboard for tracking an IP law firm's trademark, copyright, and
design matters — clients, application numbers, statuses, deadlines, applicants
and authors, plus CSV/JSON import and export. It's one self-contained
`index.html` (no build step) with a small serverless API for optional shared
storage.

The app automatically picks the best available way to save your data, in this
order, with no configuration needed to pick one yourself:

1. **A Claude artifact** — if this exact page is ever reopened as a Claude
   artifact, it saves through Claude's artifact API, unchanged from that
   experience.
2. **A shared team database** — if you've added one (see step 3 below), so
   everyone with the access key sees the same live data.
3. **This browser's local storage** — always available, zero setup, the
   fallback if neither of the above applies.

You'll almost always be using tier 2 or 3 once this is deployed to Vercel.

## 1. Quick start (zero setup, per-browser storage)

1. Push this repository to GitHub.
2. In [Vercel](https://vercel.com), click **Add New -> Project** and import
   the repo. Leave all build settings on their defaults — there is no
   framework and no build step, Vercel will detect that automatically.
3. Click **Deploy**.

That's it — the app works immediately. Data is saved to `localStorage` in
each visitor's own browser.

**Important:** in this mode, different people (or the same person on a
different device or browser) will each see their **own, independent** copy of
the data. If your team needs everyone to see the same live ledger, do step 2
below.

## 2. Optional: a shared team database

This lets everyone who has the access key see and edit the same live data.

### Primary Database: Supabase (PostgreSQL)

1. Create a table in your Supabase project's SQL Editor:
   ```sql
   create table if not exists lextria_state (
     id text primary key,
     state jsonb not null,
     updated_at timestamp with time zone default timezone('utc'::text, now()) not null
   );
   ```
2. In your Vercel project, go to **Settings -> Environment Variables** and add:
   - `SUPABASE_URL`: your Supabase Project URL (e.g. `https://xxx.supabase.co`)
   - `SUPABASE_SERVICE_ROLE_KEY`: your `service_role` secret key
   - `LEXTRIA_API_KEY`: a long, random secret password of your choice to gate team access
3. To seed or restore your portfolio data into Supabase:
   ```bash
   node scripts/seed-supabase.js "<SUPABASE_URL>" "<SUPABASE_SERVICE_ROLE_KEY>"
   ```

*(Upstash Redis via `KV_REST_API_URL` / `KV_REST_API_TOKEN` remains supported as a legacy fallback).*

If you skip this section entirely, the app keeps working fine in
`localStorage`-only mode from step 1 — nothing breaks.

## 3. Security — what's real protection and what isn't

This mirrors the same honest framing the app itself uses for its login
screen, extended to cover the shared-backend key too:

- **The on-page login passphrase** (Settings -> Login passphrase) is a
  light UI deterrent, not real access control. Anyone with the link can
  still read this page's full source — including the ledger data currently
  loaded into it — via their browser's developer tools. It only keeps the
  dashboard from being visible to someone who glances at an unattended
  screen or stumbles onto an open link.
- **The shared-backend access key** (`LEXTRIA_API_KEY`) is real, if
  lightweight, access control — it's checked server-side before any read or
  write to the shared database, so someone without it cannot see or change
  your shared data through the API. It is not enterprise-grade: it's a
  single shared secret with no per-user accounts, rotation, or audit log.
- If you leave `LEXTRIA_API_KEY` **unset** while a shared backend is
  connected, the API has **no access control at all** — anyone who finds
  your deployment URL can read and overwrite the shared ledger. Set a key
  before putting real client data behind a shared backend.
- For real client/matter data, also:
  - Keep the GitHub repository **private**.
  - Never commit real client data into the repo itself — the seed data
    ships in `index.html` (see below) purely as a starting point; the data
    you actually work with lives in Redis or `localStorage`, never in git,
    once you've started using the app.
  - Consider Vercel's built-in **Deployment Protection** (password or SSO,
    available on paid plans) for an extra layer if the data is sensitive.

## 4. Where the starter data comes from, and how to change it

The ledger's starting data (clients and matters shown the very first time
someone opens the app, before anything is saved) is embedded directly in
`index.html`, inside:

```html
<script id="app-state" type="application/json">...</script>
```

**This currently contains what looks like a real client's trademark
portfolio** (client name, brand names, application numbers, statuses) carried
over from the dashboard this repo was built from. Before you deploy this
publicly or hand the link to anyone outside your firm, decide whether that's
meant to ship as-is or should be scrubbed/replaced first:

- **To start empty:** replace the JSON inside that `<script>` tag with
  `{"clients": [], "records": [], "nextClientSeq": 1, "nextRecordSeq": 1, "log": []}`.
- **To start with different sample/starter clients:** edit that same JSON
  block directly, following the existing shape (each record has `clientId`,
  `ipType`, `brand`, `cls`, `appno`, `status`, etc. — the easiest way to see
  the full shape is to look at an existing record).

This seed data is only ever used the very first time a given browser (or the
shared backend, if connected) has no saved state yet — every add/edit/import
afterward is what actually persists.

## Local development

There's no build step. To preview the static UI only (no shared-backend API,
so it runs in `localStorage` mode):

```bash
npx serve .
# or: python3 -m http.server
```

To test the full app including `/api/state`, install the
[Vercel CLI](https://vercel.com/docs/cli) and run:

```bash
npm install
vercel dev
```
