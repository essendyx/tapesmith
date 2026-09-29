# Security policy

## Supported versions

Only the latest release of Tapesmith receives security fixes.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private vulnerability
reporting instead ("Security" tab of the repository, "Report a vulnerability"). Include the
version, steps to reproduce and the impact you expect. You will get an answer as soon as possible,
usually within a week.

## Scope and design

- The print service binds to `127.0.0.1` by default. LAN access is opt in, limited to configured
  private networks and requires an API token.
- Configuration files contain only references to secrets (Windows Credential Manager, files or
  environment variables), never the secrets themselves.
- Updates are verified with Ed25519 signatures before they are installed.

Issues in third party components should be reported to the respective projects.
