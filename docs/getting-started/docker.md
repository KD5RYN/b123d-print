# Docker

The container is the sandbox: no network, and it sees only the folder you mount.

```bash
docker pull ghcr.io/kd5ryn/b123d-print-mcp
```

Then point your client at Docker instead of `uvx` (Claude Desktop shown):

```json
{
  "mcpServers": {
    "b123d-print": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--network", "none",
               "-v", "/Users/you/parts:/work", "ghcr.io/kd5ryn/b123d-print-mcp"]
    }
  }
}
```

- `-i` is required (MCP talks over stdin/stdout); `--rm` removes the container afterwards.
- Your parts and exports appear in the mounted folder (`/Users/you/parts` above). Settings
  (printer, hole compensation) are kept there too, in `.config/b123d-print/`, since the
  container has no lasting home folder. The image sets `B123D_PRINT_CONFIG_IN_WORKSPACE=1` for
  this (see [Settings](../using/settings.md#environment-variables)).
- On Linux, add `"--user", "1000:1000"` (your `id -u`:`id -g`) so exported files belong to you.
- The image turns the OS sandbox off (`B123D_PRINT_SANDBOX=none`): bubblewrap cannot run inside
  a container without extra privileges, and the container already isolates the scripts.
- Tags: `latest` and each release (`ghcr.io/kd5ryn/b123d-print-mcp:0.1.0`); pin one if you
  want updates only when you choose.

## Building the image yourself

For unreleased code, or to check what goes into the image:

```bash
git clone https://github.com/KD5RYN/b123d-print && cd b123d-print
```

```bash
docker build -t b123d-print-mcp .
```

Then use `b123d-print-mcp` instead of `ghcr.io/kd5ryn/b123d-print-mcp` in the client config.

To run the image as a network service for several clients, see
[Over the network (HTTP)](http.md#in-docker). To update, see [Updating](../updating.md).
