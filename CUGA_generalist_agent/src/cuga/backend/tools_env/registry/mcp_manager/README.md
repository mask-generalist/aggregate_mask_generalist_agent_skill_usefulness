# MCPManager

A Python utility to load multiple OpenAPI schemas, spin up local SSE MCP servers, register their tools, and invoke them asynchronously.

## Features

- Fetch and parse OpenAPI definitions (JSON or YAML)
- Spin up a per-schema SSE server on a free port
- Dynamically register each tool/function with metadata
- Call any registered tool by name with parameters and headers
- Inspect available APIs and response schemas


## Example

1. **Configure**  
   Define a list of schema names and URLs:
   ```python
   schema_list = [
     {"petstore": "https://petstore3.swagger.io/api/v3/openapi.json"},
     {"myapi":   "https://example.com/path/to/openapi.yaml"}
   ]
   ```

2. **Initialize & Run**  
   ```python
   import asyncio
   from mcp_manager import MCPManager

   async def main():
       manager = MCPManager(schema_list)
       await manager.initialize_servers()
       await manager.run_all_servers()
       # List available servers
       print(manager.get_server_names())
       # Call a tool
       result = await manager.call_tool('petstore_findpetsbystatus', {"status": "available"})
       print(result)

   if __name__ == "__main__":
       asyncio.run(main())
   ```



## Methods

### `MCPManager(schema_urls: List[Dict[str, str]])`

Constructor. `schema_urls` is a list of single-key dicts mapping server name to OpenAPI URL.

### `initialize_servers() -> None`

Fetches each OpenAPI spec, builds a parser, creates an MCP server, and registers its tools.

### `run_all_servers() -> None`

Starts each MCP server in a background thread using SSE transport.

### `call_tool(tool_name: str, args: dict, headers: dict = None) -> Any`

Invoke a registered tool by name. Returns the JSON-decoded response.

### `get_server_names() -> List[str]`

List all initialized server names.

### `get_all_apis(include_response_schema: bool=False) -> Dict[str, List[dict]]`

Return all registered tools for each server. If `include_response_schema` is `True`, each tool dict gets a `responseSchema` field.
