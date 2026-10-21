# Web Technology Inspector

A cross-platform Streamlit application for analyzing
webpage scripts, network requests, third-party domains,
and Adobe Experience Manager content mappings.

## Features

- Website network inspection
- JavaScript inventory
- Third-party domain detection
- Request initiator analysis
- AEM Author content mapping
- Multiple website configurations
- Reusable AEM environments
- Environment-level token management
- Secure operating system credential storage
- CSV and JSON exports

## Requirements

Python 3.10 or newer.

## Windows

Run:

start.bat

## Linux

Run:

sh start.sh

## AEM Configuration

Open Global AEM Settings.

1. Create an AEM Author environment.
2. Add website mappings.
3. Select an environment.
4. Save an approved bearer token.
5. Open the Inspector.

Real configuration files are excluded from Git.

Public examples are provided under config/.

## Authentication

Tokens are stored through Python keyring.

Windows normally uses Windows Credential Manager.

Linux requires a configured secure keyring backend,
such as Secret Service, with an unlocked session.

No plaintext credential fallback is provided.

JWT expiry checks are advisory.

The application does not automatically refresh tokens.

## Limitations

- URL mappings are candidate paths.
- Vanity URLs and Sling mappings may require additional rules.
- AEM infinity.json endpoints may be restricted.
- Browser initiator data may not identify the exact tag rule.
- Use only with authorized websites and AEM environments.
- Do not expose the scanner as a public multi-user service
  without SSRF protection, authentication, and network isolation.

## Security

Do not commit:

- Access tokens
- Real environment configurations
- Internal website URLs
- Network exports
- Local backups
- Proprietary code or information

Review repository history before publishing.

Obtain required organizational approvals before
publishing company-developed code.

## First-Time Configuration

No manual AEM JSON configuration is required.

On first launch, the application automatically creates:

- `config/aem_environments.json`
- `config/aem_mappings.json`

Both files start with empty arrays.

Use **Global AEM Settings** to add AEM environments,
configure website mappings, and manage authentication.

Real configuration files are stored locally and excluded
from Git.

The repository contains `config/.gitkeep` so the
configuration directory exists after cloning.

AEM credentials are managed through the operating
system credential store, not JSON files.

