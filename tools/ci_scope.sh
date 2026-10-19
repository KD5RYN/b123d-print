#!/bin/sh
# Reads changed file names (one per line) on stdin and prints full=false when every one is
# docs-only (docs/, Markdown at the root, mkdocs.yml, server.json, plugin/), else full=true.
# Used by .github/workflows/ci.yml; try it with: git diff --name-only main | sh tools/ci_scope.sh
full=false
seen=false
while IFS= read -r f; do
  [ -n "$f" ] || continue
  seen=true
  case "$f" in
    docs/*|plugin/*|mkdocs.yml|server.json) ;;
    */*) full=true ;;  # Markdown below the root (e.g. the packaged AGENTS.md) is not docs-only
    *.md) ;;
    *) full=true ;;
  esac
done
[ "$seen" = true ] || full=true  # nothing listed: run everything
echo "full=$full"
