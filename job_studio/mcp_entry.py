"""Absolute-path entry point for MCP clients, independent of their working directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from job_studio.mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
