#!/usr/bin/env python3
"""
Test suite for MCP Server (SSE) integration
Tests listing applications, APIs, and calling functions via FastMCP
"""

import asyncio
import os
import json
import pytest
import pytest_asyncio
import tempfile


from cuga.backend.tools_env.registry.config.config_loader import load_service_configs
from cuga.backend.tools_env.registry.mcp_manager.mcp_manager import MCPManager

# MCP server URL for health check
MCP_SERVER_URL = "https://digitalsales-mcp.19pc1vtv090u.us-east.codeengine.appdomain.cloud/sse"

# Temporary MCP server config for testing
MCP_TEST_CONFIG = """# Standard MCP configuration format with MCP servers
# MCP servers configuration for testing
mcpServers:
  digital_sales_mcp:
    url: https://digitalsales-mcp.19pc1vtv090u.us-east.codeengine.appdomain.cloud/sse
    description: FastMCP example server for Digital Sales API integration (SSE-based)
"""


class TestMCPServer:
    """Test suite for MCP Server (SSE) integration"""

    @pytest_asyncio.fixture
    async def manager(self):
        """Setup MCPManager with MCP server configuration"""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(MCP_TEST_CONFIG)
            temp_config_path = f.name

        try:
            configs = load_service_configs(temp_config_path)
            manager = MCPManager(configs)
            await manager.load_tools()
            yield manager
        finally:
            # Clean up
            if os.path.exists(temp_config_path):
                os.remove(temp_config_path)

    @pytest.mark.asyncio
    async def test_list_applications(self, manager):
        """Test listing MCP applications"""
        applications = manager.get_server_names()
        assert len(applications) > 0

        # Find MCP server
        mcp_app = None
        for app in applications:
            if app in manager.mcp_clients:
                mcp_app = app
                break

        assert mcp_app is not None

    @pytest.mark.asyncio
    async def test_list_apis(self, manager):
        """Test listing APIs for MCP server"""
        applications = manager.get_server_names()

        # Find MCP server
        mcp_app = None
        for app in applications:
            if app in manager.mcp_clients:
                mcp_app = app
                break

        assert mcp_app is not None

        apis = manager.get_apis_for_application(mcp_app)
        assert isinstance(apis, dict)
        assert len(apis) >= 2  # At least 2 mock APIs

        # Verify API structure (standardized format)
        for api_name, api_info in apis.items():
            assert isinstance(api_info, dict)
            assert 'app_name' in api_info
            assert 'api_name' in api_info
            assert 'description' in api_info
            assert 'parameters' in api_info
            assert 'path' in api_info
            assert 'method' in api_info

    @pytest.mark.asyncio
    async def test_call_function_no_params(self, manager):
        """Test calling MCP function with no parameters"""
        applications = manager.get_server_names()

        # Find MCP server
        mcp_app = None
        for app in applications:
            if app in manager.mcp_clients:
                mcp_app = app
                break

        assert mcp_app is not None

        apis = manager.get_apis_for_application(mcp_app)

        # Find a function with no required parameters
        simple_function = None
        for api_name, api_info in apis.items():
            if isinstance(api_info, dict):
                params = api_info.get('parameters', [])
                # Check if any parameters are required
                required_params = [p for p in params if p.get('required', False)]
                if not required_params:
                    simple_function = api_name
                    break

        assert simple_function is not None

        # Call the function
        result = await manager.call_tool(simple_function, {})

        assert result is not None
        assert len(result) > 0

        content = result[0]
        assert hasattr(content, 'text')

        # The response should be a JSON string
        response_text = content.text
        assert isinstance(response_text, str)
        assert len(response_text) > 0


async def run_mcp_tests():
    """Run MCP server tests standalone"""
    print("🧪 Testing MCP Server (SSE) Integration")
    print("=" * 60)

    # Create temporary config file for MCP testing
    temp_config_path = "/tmp/mcp_test_config.yaml"
    with open(temp_config_path, 'w') as f:
        f.write(MCP_TEST_CONFIG)

    try:
        # Load MCP configuration
        configs = load_service_configs(temp_config_path)
        print(f"✅ Loaded {len(configs)} MCP service configurations")

        # Show loaded services
        for name, config in configs.items():
            print(f"   📋 {name}: {config.type} at {config.url}")

        # Initialize MCP Manager
        manager = MCPManager(configs)

        # Load tools
        print("\n🔧 Loading MCP tools...")
        await manager.load_tools()
        print("✅ MCP tools loaded successfully")

        # Test 1: List Applications
        print("\n📱 Test 1: List MCP Applications")
        applications = manager.get_server_names()
        print(f"✅ Found {len(applications)} applications: {applications}")

        # Test 2: List APIs for MCP server
        mcp_app = None
        for app in applications:
            if app in manager.mcp_clients:  # Find MCP server
                mcp_app = app
                break

        if mcp_app:
            print(f"\n🔍 Test 2: List APIs for MCP server '{mcp_app}'")
            apis = manager.get_apis_for_application(mcp_app)
            print(f"✅ Found {len(apis)} APIs")

            # Show API details (MCP format)
            for i, api in enumerate(apis[:3], 1):  # Show first 3
                if isinstance(api, dict) and 'function' in api:
                    func = api['function']
                    name = func.get('name', 'unknown')
                    desc = func.get('description', 'no description')
                    params = func.get('parameters', {})

                    print(f"   {i}. {name}")
                    print(f"      Description: {desc[:80]}{'...' if len(desc) > 80 else ''}")

                    # Show flattened parameters
                    if params and 'properties' in params:
                        props = params['properties']
                        required = params.get('required', [])
                        print(f"      Parameters: {len(props)} properties")

                        for param_name, param_info in list(props.items())[:2]:  # Show first 2
                            param_type = param_info.get('type', 'unknown')
                            is_required = param_name in required
                            desc = param_info.get('description', '')
                            print(
                                f"        - {param_name} ({param_type}) {'[required]' if is_required else '[optional]'}"
                            )
                            if desc:
                                print(f"          {desc[:60]}{'...' if len(desc) > 60 else ''}")
                    else:
                        print("      Parameters: None")

            # Test 3: Call a function via MCP
            print("\n📞 Test 3: Call MCP Function")

            # Find a simple function to call (preferably one without required params)
            simple_function = None
            for api in apis:
                if isinstance(api, dict) and 'function' in api:
                    func = api['function']
                    params = func.get('parameters', {})
                    required = params.get('required', [])
                    if not required:  # Function with no required parameters
                        simple_function = func['name']
                        break

            if simple_function:
                print(f"   Calling: {simple_function}")
                try:
                    result = await manager.call_tool(simple_function, {})
                    print("✅ MCP function call successful!")

                    # Parse and show result
                    if hasattr(result, '__iter__') and len(result) > 0:
                        content = result[0]
                        if hasattr(content, 'text'):
                            response_text = content.text
                            print(
                                f"   Response preview: {response_text[:200]}{'...' if len(response_text) > 200 else ''}"
                            )

                            # Try to parse as JSON for better display
                            try:
                                response_data = json.loads(response_text)
                                if isinstance(response_data, dict):
                                    print(f"   Response keys: {list(response_data.keys())}")
                            except Exception:
                                pass  # Not JSON, that's fine
                        else:
                            print(f"   Raw result: {content}")
                    else:
                        print(f"   Result: {result}")

                except Exception as e:
                    print(f"❌ MCP function call failed: {e}")
                    import traceback

                    traceback.print_exc()
            else:
                print("⚠️  No simple function found to test (all require parameters)")

        else:
            print("❌ No MCP server application found")

        print("\n🎉 MCP Server test completed!")

    finally:
        # Clean up temporary config file
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)


if __name__ == "__main__":
    asyncio.run(run_mcp_tests())
