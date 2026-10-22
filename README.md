# MarTech Architect Toolkit

Standalone tools for working with Adobe Experience Cloud and the wider MarTech stack.
Each folder is a self-contained app with its own README, `requirements.txt` and launcher —
clone the repo, `cd` into a tool and follow its README.

| Tool | What it does |
|---|---|
| [adobe-access-manager](adobe-access-manager/) | Validates users against your domain, previews idempotent access changes and assigns Adobe user groups through UMAPI |
| [aep-monitor](aep-monitor/) | Health dashboard for AEP dataflows, Data Collection / Tags and CJA connections, with history and alerts |
| [aem-groovy-runner](aem-groovy-runner/) | Runs Groovy scripts on AEM as a Cloud Service through the Groovy Console HTTP API |
| [web-technology-inspector](web-technology-inspector/) | Inspects a page's scripts, network requests, third-party domains and AEM content mappings |
| [cja-mcp](cja-mcp/) | Streamlit reporting UI over Adobe's Customer Journey Analytics MCP server |
| [target-mcp](target-mcp/) | Streamlit reporting UI over Adobe's Target MCP server, with OAuth login |
| [mailgun-log-viewer](mailgun-log-viewer/) | Queries Mailgun's Events API across all domains with filters Mailgun doesn't offer server-side |

## History

`adobe-access-manager`, `aep-monitor`, `aem-groovy-runner`, `mailgun-log-viewer` and
`WebTechnologyInspector` used to be separate repositories, and `cja-mcp` / `target-mcp`
lived in `ai-share`. They were merged here with their full commit history; the old
repositories are archived and point back to this one.
