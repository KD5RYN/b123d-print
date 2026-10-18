# Advanced: run it on another machine

Most people run the MCP server on the same computer as their AI assistant: that is the
[Quick start](../getting-started/quick-start.md), and it needs nothing on this page. Read on if
the parts should live somewhere else, many agents should share one server, or you want the
strongest isolation.

## Which mode?

| Mode | Use it for | Login | Files come back by |
| --- | --- | --- | --- |
| [Local (stdio)](../getting-started/mcp-clients.md) | everything on one machine (the normal setup) | none needed | they are already on your disk |
| [SSH](../getting-started/ssh.md) | a home server and a few of your own machines | your SSH key, one line per machine in `authorized_keys` | `b123d-print pull`, or `export(embed=true)` |
| [HTTP](../getting-started/http.md) | many agents at once, eval runs, a shared service | a named token per tool, TLS from a reverse proxy | download links |

[Docker](../getting-started/docker.md) runs the server in a container, either locally over
stdio (the strongest isolation, and the way to get one on Windows) or as the HTTP service with
Compose.
