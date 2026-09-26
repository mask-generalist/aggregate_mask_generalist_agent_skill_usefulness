lsof -ti:8000,8001,7860 | xargs kill -9
export MCP_SERVERS_FILE=./src/system_tests/e2e/config/mcp_servers.yaml
uv run digital_sales_openapi &
uv run registry