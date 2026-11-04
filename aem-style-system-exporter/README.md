# AEM Style System Exporter

Exports an AEM site's Style System into Excel: every component policy and its
styles, the templates that use each policy, and optionally the front-end CSS
those styles' classes reach and the theme tokens (CSS custom properties). Every
export is kept, so each workbook lists what changed since the last one, and a
compare page shows the differences between any two exports, e.g. stage and prod.

All AEM access is read-only `GET` requests.

## Prerequisites

- Node.js 22 or later (the scripts check and say so)
- An AEM author URL and a Local Development Token with read access to the
  site's `/conf` policies and templates
- Optional: the front-end project, for theme CSS and tokens

## Setup

1. Copy `.env.example` to `.env`.
2. Set `AEM_AUTHOR_URL` and paste the Local Development Token into
   `AEM_LOCAL_TOKEN` (no `Bearer` prefix).
3. Set `AEM_POLICY_ROOT` and `AEM_TEMPLATE_ROOT` for your site
   (`/conf/<site>/settings/wcm/policies` and `.../templates`).
4. Optionally set `FE_PROJECT_PATH` and comma-separated `FE_THEMES`.

Dependencies are installed by the scripts on first run (or run `npm install`).

## Export

```
export.bat          # Windows
sh export.sh        # macOS / Linux
```

Each run:

1. Reads the policies and templates from AEM author.
2. Reads the front-end CSS, if `FE_PROJECT_PATH` is set, and maps each style's
   classes to the CSS rules that use them.
3. Saves the run to the history and compares it with the previous one.
4. Writes `output/EWP_Style_System_Export.xlsx`.

Exit code 0 means complete, 2 means completed with warnings (see the console and
`output/validation-report.json`), 1 means it failed.

### What's read from AEM

- **Policies** under `AEM_POLICY_ROOT`, with their style groups and styles.
- **Templates** under `AEM_TEMPLATE_ROOT`: each template's title and status
  (`jcr:content`) and its policy mappings (`policies`). Structure and initial
  content aren't read.
- A template policy reference that doesn't resolve to an exported policy is
  checked in AEM, and marks the export incomplete (exit code 2); see
  `missingReferences` in `validation-report.json`.

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

Every export is saved in `output/history/<environment>/<time>/`; the
environment is the author host, and the last `HISTORY_KEEP` (default 20) are
kept per environment. The **Changes** sheet compares the export with the
previous one of the same environment and repository roots:

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

## Compare page

```
compare.bat         # Windows
sh compare.sh       # macOS / Linux
```

Opens `http://127.0.0.1:8510/` in the browser (`COMPARE_UI_PORT` to change; the
next free port is used if it's taken). Pick a **Before** and an **After** export
(by default the previous and latest export of the newest environment), filter by
area, change type or text, and **Download Excel**. Compare two environments,
e.g. stage and prod, by exporting each (change `AEM_AUTHOR_URL` in `.env`) and
picking one of each. The address keeps the two exports, so it can be bookmarked.
Keep the console open while using the page; stop it with Ctrl+C.

The page listens on this machine only, answers only requests addressed to it,
and only reads saved exports.

The same on the command line (`npm run compare -- …` works too):

```
compare.bat --list
compare.bat author-p1-e2.adobeaemcloud.com~1 author-p1-e2.adobeaemcloud.com
compare.bat <stage-host> <prod-host>
```

Each argument is a folder, `<environment>/<time>` as `--list` prints it,
`<environment>` for its latest export, or `<environment>~1` for the one before
(`~2`, … further back). The result is written to `output/comparisons/` as a
workbook and JSON.

## Settings (`.env`)

| Setting | Default | Purpose |
|---|---|---|
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
| `HISTORY_KEEP` | 20 | Exports kept per environment |
| `COMPARE_UI_PORT` | 8510 | First port tried by the compare page |

## Output

| Path | Contents |
|---|---|
| `output/EWP_Style_System_Export.xlsx` | The workbook |
| `output/*.json` | The run's raw data: policies, templates, policy usage, validation report, front-end data, CSS mapping, changes |
| `output/history/` | Saved exports, for the Changes sheet and the compare page |
| `output/comparisons/` | Comparisons made on the command line |

`output/` is git-ignored.

## Development

```
npm test            # comparison, history and compare page tests (node:test)
npm run check       # syntax check of every script
```

Each step also runs on its own: `npm run export:aem`, `export:fe`, `export:map`,
`export:history`, `export:excel`.

## Security

Never commit `.env`. Treat the output as internal configuration data, and review
it before sharing.
