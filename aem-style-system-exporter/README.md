# EWP AEM Style System + optional FE theme export

## Prerequisites
Node.js 22+ and access to the existing AEM exporter `src/exporter.js`.

## Setup
1. Copy `.env.example` to `.env`; paste the local development JWT into `AEM_LOCAL_TOKEN` (no `Bearer` prefix).
2. Set AEM Author URL and repository roots.
3. Optionally set `FE_PROJECT_PATH` and comma-separated `FE_THEMES`.
4. Run `npm install` in this folder.
5. Run `export.bat` (Windows) or `sh export.sh` (Unix).

The existing `src/exporter.js` must be copied from your current working project; this package intentionally does not replace it. It must produce policies.json, policy-usage.json, and validation-report.json in `output/`, and return 0 or 2 for completed exports.

Crawling: MAX_NODES applies to the policy root and the template root separately. Templates are scanned only under `{template}/policies`. FETCH_DEPTH (default 3) sets how many levels each request returns, and CONCURRENCY (default 4) how many requests run in parallel; lower them if AEM Author is under load. Any unresolved template policy reference marks the export incomplete (exit code 2); see `missingReferences` in validation-report.json.

FE_BUILD=false uses `dist/clientlib-{theme}/{theme}.css`. FE_BUILD=true runs FE_BUILD_COMMAND in FE_PROJECT_PATH first. Optional FE_SHARED_CSS accepts comma-separated paths relative to FE_PROJECT_PATH (or absolute paths).

The generated Excel has Style System, Policy Summary, Changes (see below), and a Theme tab per selected theme. CSS extraction reads compiled CSS custom properties. It does NOT extract original Sass `$variables`, nor guarantee browser-computed styles. For those, a separate SCSS source analysis or browser evaluation is needed.

Missing FE configuration produces AEM-only Excel. Missing CSS for some themes is warned about. AEM extraction warnings are retained in JSON and console output, not an Excel validation tab. Template association means a reference was found in the scanned configuration; it does not prove a page uses the style. No Style IDs are included in Excel.

## Changes between exports

Every export is saved as a snapshot in `output/history/<environment>/<time>/` (the last `HISTORY_KEEP`, default 20, per environment; the environment is the AEM author host). The workbook's **Changes** sheet lists what changed since the previous export of the same environment and repository roots:

- **Template**: added, removed, title or status (enabled, disabled, draft) changed
- **Template policy**: the policy a template assigns to a component added, removed or changed
- **Policy**: added, removed, or its own properties changed (repository bookkeeping such as `jcr:lastModified` is ignored)
- **Style**: added, removed, or label, CSS classes or group changed. Styles are matched by their style ID, so reordering them isn't a change
- **Theme token** and **Style CSS**: token values, and the CSS a style's classes reach, when front-end CSS was read in both exports

Each row shows who last modified the template or policy and when, where AEM records it. The first export of an environment has nothing to compare with yet.

Compare any two saved exports, e.g. stage with prod:

```
npm run compare -- --list
npm run compare -- author-p1-e2.adobeaemcloud.com~1 author-p1-e2.adobeaemcloud.com
npm run compare -- <stage-host> <prod-host>
```

Each argument is a folder, `<environment>/<time>` as `--list` prints it, `<environment>` for its latest export, or `<environment>~1` for the one before (`~2`, … further back). The result is written to `output/comparisons/` as a workbook and JSON. A comparison with an incomplete export says so: missing data then shows as removals.

Security: never commit `.env`. Treat output as internal configuration data. Review before sharing.
