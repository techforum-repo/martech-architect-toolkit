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

FE_BUILD=false uses `dist/clientlib-{theme}/{theme}.css`. FE_BUILD=true runs FE_BUILD_COMMAND in FE_PROJECT_PATH first. Optional FE_SHARED_CSS accepts comma-separated paths relative to FE_PROJECT_PATH (or absolute paths).

The generated Excel has Style System, Policy Summary, and a Theme tab per selected theme. CSS extraction reads compiled CSS custom properties. It does NOT extract original Sass `$variables`, nor guarantee browser-computed styles. For those, a separate SCSS source analysis or browser evaluation is needed.

Missing FE configuration produces AEM-only Excel. Missing CSS for some themes is warned about. AEM extraction warnings are retained in JSON and console output, not an Excel validation tab. Template association means a reference was found in the scanned configuration; it does not prove a page uses the style. No Style IDs are included in Excel.

Security: never commit `.env`. Treat output as internal configuration data. Review before sharing.
