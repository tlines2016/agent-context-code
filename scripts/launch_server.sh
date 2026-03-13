#!/usr/bin/env bash
# GPU-aware MCP server launcher — delegates to launch_server.py
exec python3 "$(dirname "$0")/launch_server.py" "$@"
