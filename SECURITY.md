# Security policy

## Supported version

Security fixes are provided for the latest published release. Update before reporting an issue that only affects an older version.

## Reporting a vulnerability

Do not publish exploitable details in a public issue. Use GitHub's **Security → Report a vulnerability** form (private vulnerability reporting) in this repository. Include the affected version, configuration, reproduction steps and impact. Do not include real photos, passwords, session cookies or Funnel URLs.

## Security model

- Internet-facing installations must use HTTPS through a maintained reverse proxy or Tailscale Funnel. Plain HTTP is intended only for trusted local networks.
- Administration uses a password, rate limiting and optional TOTP two-factor authentication. Albums have separate passwords and revocable guest links.
- Same-origin checks and session-bound CSRF tokens protect browser state changes; cookies are HTTP-only, SameSite and Secure behind HTTPS. CSP, HSTS on HTTPS, frame, MIME, referrer and permissions headers reduce browser attack surface.
- Uploads have size, extension and file-signature validation. Originals are never executed and responses use `nosniff`.
- The supplied Compose configurations enable `no-new-privileges`, drop all Linux capabilities except the three needed to adopt the data-volume owner at startup (`CHOWN`, `SETUID`, `SETGID`), use a read-only root filesystem, isolate `/tmp`, limit processes and keep persistent data in a dedicated volume. The launcher drops privileges before starting the web server.
- Dependencies are monitored by Dependabot. CI runs application, browser, container and dependency-audit checks.

Certificate pinning is intentionally not used: users connect to their own changing LAN, reverse-proxy or Funnel certificates. Android relies on the operating system trust store and rejects certificate errors; the app warns about HTTP addresses.

The stored server address and profile names are not credentials. Android private app storage is sandboxed and excluded from Android backups. Passwords and session cookies are held by the system WebView cookie store rather than profile settings.
