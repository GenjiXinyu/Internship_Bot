# Internship Bot

Every 4 hours this bot checks the career sites of the companies in
[`companies.yaml`](companies.yaml) for US engineering internships and co-ops. When it
finds a posting you haven't seen, it:

1. adds a row to your Google Sheet tracker (status "Not yet Applied", with the date
   the company posted it and the date the bot found it), and
2. emails you the company, position and apply link.

It also fills in **Date Posted** for postings you logged in the tracker yourself.

The first run is a catch-up: every engineering internship open right now goes into the
sheet and arrives in one email. After that you only hear about new postings.

## Where the postings come from

- **Directly from each company's job board** (Greenhouse, Lever, Ashby, Workday,
  Pinpoint and others). These are the fastest.
- **The [SimplifyJobs internship list](https://github.com/SimplifyJobs/Summer2027-Internships)**,
  a community-maintained list, as a backup for every company. It's the main source
  for companies whose career sites can't be read directly (Honeywell, Howmet,
  Iridium, Joby, Safran and others), so those can arrive up to a day later.

## One-time setup (about 15 minutes)

This repo is public, so nothing personal is in the code. You add four secrets instead.
GitHub stores them encrypted; they never appear in the code or the run logs.

All four go in: **Settings → Secrets and variables → Actions → New repository secret**.

### 0. Where to send alerts, and which sheet

| Name | Secret |
|---|---|
| `EMAIL_TO` | the email address that should get the alerts |
| `SHEET_ID` | the tracker's ID: the part of its link between `/d/` and `/edit` |

### 1. Gmail app password (for sending the email)

1. Turn on 2-Step Verification for your Google account if it isn't already:
   <https://myaccount.google.com/signinoptions/twosv>
2. Create an app password: <https://myaccount.google.com/apppasswords>. Name it
   "Internship Bot". Google shows a 16-letter password; copy it.
3. In this repo on GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GMAIL_APP_PASSWORD`
   - Secret: the 16-letter password (spaces don't matter)

The email is sent from your own Gmail to yourself. (Optional: to send from a
different Gmail account, add a secret `GMAIL_ADDRESS` with that address and create the
app password on that account instead.)

### 2. Google service account (so the bot can edit your sheet)

A service account is a robot Google user. You share the tracker with it like you'd
share with a person.

1. Go to <https://console.cloud.google.com/> and sign in. Create a project (top bar →
   project picker → **New project**, name it "internship-bot").
2. Turn on the Sheets API: open
   <https://console.cloud.google.com/apis/library/sheets.googleapis.com> and click **Enable**.
3. Create the service account: **IAM & Admin → Service Accounts → Create service account**.
   Name it "internship-bot", click **Done** (no roles needed).
4. Click the new account → **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
5. Open the tracker sheet → **Share** → paste the service account's email (it looks like
   `internship-bot@your-project.iam.gserviceaccount.com`) → give it **Editor** → uncheck
   "Notify people" → **Share**.
6. Back in GitHub → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Secret: paste the **entire contents** of the downloaded `.json` file

Keep the `.json` file private and don't commit it to the repo.

### 3. Turn it on

GitHub → **Actions** tab → **Internship scan** → **Run workflow**.

- Tick **Dry run** to only list what it finds (nothing is changed and no email is sent).
- Leave it unticked for the real first run: the sheet fills in and the catch-up email arrives.

After that it runs on its own every 4 hours.

## Everyday use

- **Mark your progress in the sheet.** Change "Application Status" (dropdown) and fill in
  "Date Applied". The bot never edits those columns.
- **Rows you delete stay deleted.** The bot remembers every posting it has seen in the
  "Seen Postings" tab, so it won't add them back.
- **Add a company:** add an entry to `companies.yaml`. The quickest way to find a company's
  job board is to open one of its postings and look at the link:
  - `job-boards.greenhouse.io/<token>/...` → `{greenhouse: <token>}`
  - `jobs.lever.co/<site>/...` → `{lever: <site>}`
  - `jobs.ashbyhq.com/<board>/...` → `{ashby: <board>}`
  - `<tenant>.<wd5>.myworkdayjobs.com/<site>/...` → `{workday: {tenant: ..., wd: ..., site: ...}}`
- **Check that it's working:** Actions tab → the latest run → "Scan, update sheet, email"
  shows each source with `[ok]` or `[FAIL]`. A failing source is still covered by the
  SimplifyJobs list.

## Running it on your own computer (optional)

```bash
pip install -r requirements.txt
python -m bot.main --dry-run        # list what it finds
python -m pytest                    # run the tests
```
