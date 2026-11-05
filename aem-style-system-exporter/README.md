# AEM Style System Exporter

Exports an AEM site's Style System into Excel: every component policy and its
styles, the templates that use each policy, and optionally the front-end CSS
those styles' classes reach and the theme tokens (CSS custom properties). Every
export is kept, so each workbook lists what changed since the last one. A local
app runs exports, manages each environment's settings, and compares any two
runs: on one environment over time, or between environments such as stage and prod.

All AEM access is read-only `GET` requests.

## Prerequisites

- Node.js 22 or later (the scripts check and say so)
- An AEM author URL and a Local Development Token with read access to the
  site's `/conf` policies and templates
- Optional: the front-end project, for theme CSS and tokens

## Start

```
start.bat           # Windows
sh start.sh         # macOS / Linux
```

Opens the app at `http://127.0.0.1:8510/` (the next free port if it's taken;
`COMPARE_UI_PORT` in `.env` to change). Keep the console open while using it;
Ctrl+C stops it, and any export it started.

| Tab | |
|---|---|
| **Run** | Pick an environment, **Run export**, and follow the log as it runs. When it's done: the run's status, **Download workbook**, and **Show changes** since the previous run. Cancel stops a run. One run at a time per environment |
| **History** | An environment's runs: status, changes since the previous run, the settings file and machine it ran on, workbook download. Pick any two to compare, or delete a run |
| **Compare environments** | A run of one environment against a run of another, e.g. prod and stage |
| **Settings** | Add and edit environments: author URL, token, roots, front end and limits. **Test connection** makes one read from AEM with the token and says whether it works |

The comparison shows counts per area, filters by area, change type or text, and
downloads as Excel. The address keeps the tab and the two runs, so it can be
bookmarked.

The app runs on this machine only. It answers only requests addressed to
`127.0.0.1` / `localhost`, and anything that changes something (saving
settings, running, cancelling, testing a connection) needs a key only the page
it served has, so another website can't trigger it. The token is write-only:
the app shows whether it's set and when it expires, never the value.

Everything the app does is also available without it (below), e.g. for
scheduled exports.

## Setup

Add environments under **Settings** in the app, or by hand: one settings file
per environment, `.env.prod`, `.env.stage`, … copied from `.env.example` (or
`.env` if you only use one). In each:

1. Set `AEM_AUTHOR_URL` and paste the Local Development Token into
   `AEM_LOCAL_TOKEN` (no `Bearer` prefix).
2. Set `AEM_POLICY_ROOT` and `AEM_TEMPLATE_ROOT` for your site
   (`/conf/<site>/settings/wcm/policies` and `.../templates`).
3. Optionally set `FE_PROJECT_PATH` and comma-separated `FE_THEMES`.

The settings files are git-ignored. Dependencies are installed by the scripts on
first run (or run `npm install`).

## Environments

Each AEM author is one environment. Its id comes from the author URL:
`author-p12345-e67890.adobeaemcloud.com` is `p12345-e67890` (other hosts use the
host name). Its name is the settings file's (`prod` for `.env.prod`), or
`AEM_ENV_NAME` if set, and is shown as `prod (p12345-e67890)`. A name belongs to
one author URL: using it for another stops the run. Two settings files for the
same author URL share one environment and its history; `AEM_ENV_NAME` renames it.

## Export

From the app's **Run** tab, or:

```
export.bat prod         # Windows: uses .env.prod
sh export.sh prod       # macOS / Linux
export.bat              # uses .env
```

Each run gets a folder of its own, so nothing is ever overwritten, also when
switching environments or exporting two at once:

1. Reads the policies and templates from AEM author.
2. Reads the front-end CSS, if `FE_PROJECT_PATH` is set, and maps each style's
   classes to the CSS rules that use them.
3. Compares the run with the environment's previous one.
4. Writes the workbook into the run folder, named after the environment and
   run, e.g. `Style-System_prod_2026-11-05_103012Z.xlsx`.

The console ends with the run's status and the workbook's path. Exit code 0
means complete, 2 completed with warnings (see the console and the run's
`data/validation-report.json`), 1 failed.

### Runs

```
output/environments/
  p12345-e67890/                     prod
    environment.json                 id, name, author URL
    2026-11-05_103012Z/              one run (UTC time; -2 if two start in the same second)
      run.json                       status, times, machine, roots, counts, changes
      Style-System_prod_2026-11-05_103012Z.xlsx
      data/                          the run's data: policies, templates, policy usage, changes, …
  p12345-e11111/                     stage
output/comparisons/                  comparisons made on the command line
```

A run's status is **complete** (everything was read), **incomplete** (some
nodes couldn't be read, or a crawl limit was reached; the run says which),
**failed** (with the error), **interrupted** or **running**. Only
complete and incomplete runs are compared. The last `HISTORY_KEEP` runs (default
20) are kept per environment, workbooks included. The large front-end data
files are removed once the workbook is written (`KEEP_RAW_DATA=true` keeps them);
comparisons use the theme tokens and CSS fingerprints saved with each run.

To delete a run (its workbook and data), use **Delete** in the History tab (it
asks to confirm) or `compare.bat --delete prod/2026-11-05_103012Z` with the run
id `--list` shows. A run still in progress can't be deleted; an environment's
folder goes with its last run. With a shared history, a deleted run is gone for
everyone.

Exports saved by an earlier version (`output/history/`) are moved into this
layout on the next export or compare.

### A shared history

`HISTORY_DIR` (e.g. a network drive or a synced Teams/SharePoint folder) keeps
environments, runs and comparisons there instead of `output/`, so a team sees
each other's runs; each run records the machine it ran on. Runs are never
changed once finished, so people can export at the same time.

### What's read from AEM

- **Policies** under `AEM_POLICY_ROOT`, with their style groups and styles.
- **Templates** under `AEM_TEMPLATE_ROOT`: each template's title and status
  (`jcr:content`) and its policy mappings (`policies`). Structure and initial
  content aren't read.
- A template policy reference that doesn't resolve to an exported policy is
  looked up the way AEM does: the site's configuration, its parent
  configurations (`/conf/site/us` falls back to `/conf/site`), then
  `/conf/global`, `/apps/conf` and `/libs/conf`. One found there is listed as
  inherited (`outsideRootReferences` in `validation-report.json`; its styles
  aren't in this export).
- One found nowhere is a **finding about AEM**, not a problem with the
  export: the template points to a policy that doesn't exist, so AEM uses no
  policy for that component. The run is still complete; the finding is listed
  with it (console `[FINDING]`, under the run in the app,
  `missingReferences` in `validation-report.json`), and the log names it:

  ```
  [CHECK] Missing in AEM: /conf/site/settings/wcm/policies/site/components/page/policy_123
          Used by template article › (page): the template points to a policy that doesn't exist. …
  ```

  AEM answers 404 for such a policy, which is why the report shows a 404 for
  it. Fix the template's policy for that component in the template editor, or
  ignore it if the component isn't used.
- In a template's policy mappings, AEM's JSON also shows the mapped policy's
  `jcr:content` and `cq:styleGroups`; they aren't nodes of the template
  (fetching them answers 404) and aren't read.
- Access-control nodes (`rep:policy`, …) aren't read. A `[FAILED] … HTTP 404`
  line during the crawl means a node was listed but couldn't be read, usually
  because of the token user's permissions; the run is then incomplete.

### Front-end CSS

`FE_BUILD=false` reads `dist/clientlib-{theme}/{theme}.css` in `FE_PROJECT_PATH`;
`FE_BUILD=true` runs `FE_BUILD_COMMAND` there first. `FE_SHARED_CSS` adds
comma-separated CSS files (relative to `FE_PROJECT_PATH`, or absolute) to every
theme. Without front-end settings the workbook is AEM-only; a theme without CSS
is warned about and shows "FE unavailable".

This reads compiled CSS custom properties. It does not read Sass `$variables`,
nor compute what a browser would apply; that needs a separate SCSS analysis or
browser evaluation.

## The workbook

| Sheet | Contents |
|---|---|
| Style System | One row per style (and theme): component, policy, group, style, CSS classes, templates using the policy, the CSS rules its classes reach, and how they match: **Direct** (the style's own classes), **Conditional** (with other classes), **Mixed** or **Not Found** |
| Policy Summary | One row per policy: component, number of styles, templates referencing it |
| Changes | What changed since the previous export (below) |
| Theme - *name* | The theme's tokens: category, name, value, selector or context, source file |

"Template" association means a reference was found in the template's policy
mappings; it doesn't prove a page uses the style. Style IDs aren't included.

## Changes between exports

The workbook's **Changes** sheet compares the run with the previous complete or
incomplete run of the same environment and repository roots:

- **Template**: added, removed, title or status (enabled, disabled, draft) changed
- **Template policy**: the policy a template assigns to a component added, removed or changed
- **Policy**: added, removed, or its own properties changed (repository
  bookkeeping such as `jcr:lastModified` is ignored)
- **Style**: added, removed, or label, CSS classes or group changed. Styles are
  matched by their style ID, so reordering them isn't a change
- **Theme token** and **Style CSS**: token values, and the CSS a style's
  classes reach, when front-end CSS was read in both exports

Each row shows who last modified the template or policy and when, where AEM
records it. The first export of an environment has nothing to compare with; the
second lists what changed since. If either export was incomplete, the sheet
says so: missing data then shows as removals.

Between environments, a policy created separately on each (rather than moved
in a content package) has a different `policy_<id>`, so it shows as removed on
one side and added on the other; the comparison points these out.

## Compare

In the app's **History** tab (one environment over time, by default the
previous and latest run) or **Compare environments** tab (latest of each by
default). `compare.bat` / `sh compare.sh` without arguments opens the app on
History.

On the command line (`npm run compare -- …` works too):

```
compare.bat --list          # environments and their runs
compare.bat prod~1 prod     # over time: the previous prod run against the latest
compare.bat prod stage      # between environments: latest of each
compare.bat --delete prod/2026-11-05_103012Z   # delete that run
```

A run is `<environment>` (its latest complete or incomplete run),
`<environment>~1` (the one before, `~2`, …), `<environment>/<run id>` as
`--list` prints it, or a run folder; the environment is its name or id. The
result is written to `comparisons/` as a workbook and JSON.

## Settings (`.env.<environment>`)

| Setting | Default | Purpose |
|---|---|---|
| `AEM_ENV_NAME` | the file's | Environment name, e.g. `prod`; renames the environment |
| `AEM_AUTHOR_URL` | | AEM author, HTTPS |
| `AEM_LOCAL_TOKEN` | | Local Development Token, without `Bearer` |
| `AEM_POLICY_ROOT` | | `/conf/<site>/settings/wcm/policies` |
| `AEM_TEMPLATE_ROOT` | | `/conf/<site>/settings/wcm/templates` |
| `MAX_NODES` | 15000 | Nodes read per root (policies and templates each); more marks the export incomplete |
| `MAX_DEPTH` | 30 | Deepest level read below a root |
| `FETCH_DEPTH` | 3 | Levels per request; AEM answering "too large" falls back to one |
| `CONCURRENCY` | 4 | Requests at a time; lower it if author is busy |
| `REQUEST_TIMEOUT` | 30000 | Milliseconds per request |
| `PROGRESS_INTERVAL` | 25 | Progress line every this many nodes |
| `FE_PROJECT_PATH` | | Front-end project folder; empty for AEM-only |
| `FE_THEMES` | corporate | Comma-separated theme names |
| `FE_BUILD` | false | Build the front end first |
| `FE_BUILD_COMMAND` | npm run build | The build command |
| `FE_SHARED_CSS` | | Extra CSS files for every theme |
| `HISTORY_KEEP` | 20 | Runs kept per environment |
| `HISTORY_DIR` | `output` | Where environments, runs and comparisons are kept, e.g. a shared folder |
| `KEEP_RAW_DATA` | false | Keep the large front-end data files in each run |
| `COMPARE_UI_PORT` | 8510 | First port tried by the app |

The app and `compare.bat` read `.env` for `HISTORY_DIR` and `COMPARE_UI_PORT`,
and pass the app's `HISTORY_DIR` to the runs they start; set it in `.env`. The
app never loads a settings file into its own environment, so a run gets exactly
its environment's settings.

`output/` is git-ignored.

## Development

```
npm start           # the app (as start.bat)
npm test            # store, comparison, settings and app tests (node:test)
npm run check       # syntax check of every script
```

Each step also runs on its own with `.env` (`npm run export:aem`, `export:fe`,
`export:map`, `export:excel`), writing to `output/work/`.

## Security

Never commit the `.env` files (they're git-ignored). Treat the output as internal configuration data, and review
it before sharing.
