# Security

postloom runs on your own computer and keeps your data there. Its web server listens only
on `127.0.0.1`, refuses requests that aren't addressed to localhost, and requires a custom
header on every request that changes something, so other websites can't use it. API keys
are stored in `config.json` in your Postloom folder (readable only by you) and are never
sent to the browser.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: on the
repository page, open **Security** -> **Report a vulnerability**. Include what you found,
how to reproduce it and the version (`postloom --version`).

You'll get an answer within a week. Fixes are released as soon as they're ready and
credited in the changelog unless you'd rather not be named.

## Supported versions

Only the latest release gets security fixes. Run the install line again to update.
