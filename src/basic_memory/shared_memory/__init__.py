"""Fork features for one shared memory across MCP clients.

Each feature lives in its own module and stays config-gated. Import the
specific module you need; this package does not re-export them, so a CLI
command does not pull the HTTP stack and vice versa.
"""
