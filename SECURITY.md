# Security policy

b123d-print runs code that an AI writes (part scripts) and can serve several people from one
server, so security reports are welcome and taken seriously.

## Reporting a vulnerability

**Please do not open a public issue.** Report it privately instead:

- on GitHub: the repository's **Security** tab → **Report a vulnerability**
  (<https://github.com/KD5RYN/b123d-print/security/advisories/new>).

Include what you found, the version (`b123d-print --version`), the mode (stdio, SSH, HTTP,
Docker), and the steps to reproduce if you have them. You will get an answer within a few days.
A fix is developed privately, released, and then published as a GitHub security advisory that
credits you, unless you prefer not to be named.

## What counts

Anything that lets a part script, a client or a link reach beyond what it should, for example:

- a part script escaping the sandbox: network access, starting processes, reading or writing
  outside its own part folder;
- one token or workspace reaching another workspace's files on a shared server;
- forging or reusing signed links (`/files`, `/zip`, `/upload`, `/view`);
- reading the server's tokens or link secret;
- problems in the release pipeline or published packages.

What isolates part scripts in each mode, and its limits, is described in
[Sandbox](https://kd5ryn.github.io/b123d-print/using/sandbox/).

## Supported versions

Fixes go into the latest release. Please upgrade to it before reporting, if you can.

## Published advisories

<https://github.com/KD5RYN/b123d-print/security/advisories>
