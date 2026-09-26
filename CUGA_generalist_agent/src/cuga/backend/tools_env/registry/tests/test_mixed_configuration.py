#!/usr/bin/env python3
"""
Test suite for Mixed Configuration support
Tests both legacy OpenAPI and MCP servers in the same configuration
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

# Mixed configuration with both legacy and MCP servers
MIXED_CONFIG = """# Mixed configuration with both legacy and MCP servers
# Legacy services (maintained for backward compatibility)
services:
  - digital_sales_legacy:
      url: https://digitalsales.19pc1vtv090u.us-east.codeengine.appdomain.cloud/openapi.json
      description: Legacy Digital Sales API

# Standard MCP servers configuration
mcpServers:
  digital_sales_mcp:
    url: https://digitalsales-mcp.19pc1vtv090u.us-east.codeengine.appdomain.cloud/sse
    description: FastMCP example server for Digital Sales API integration (SSE-based)
"""


class TestMixedConfiguration:
    """Test suite for mixed configuration support"""

    @pytest_asyncio.fixture
    async def manager(self):
        """Setup MCPManager with mixed configuration"""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(MIXED_CONFIG)
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
    async def test_both_services_loaded(self, manager):
        """Test that both legacy and MCP services are loaded"""
        applications = manager.get_server_names()

        # Should have both services
        assert len(applications) == 2
        assert 'digital_sales_legacy' in applications
        assert 'digital_sales_mcp' in applications

    @pytest.mark.asyncio
    async def test_legacy_service_apis(self, manager):
        """Test legacy service APIs"""
        apis = manager.get_apis_for_application('digital_sales_legacy')

        # Should have 4 APIs in legacy format
        assert len(apis) == 4

        # Verify legacy format (dict of API objects)
        api_list = list(apis.values()) if isinstance(apis, dict) else apis
        for api in api_list:
            assert isinstance(api, dict)
            assert 'api_name' in api
            assert 'method' in api
            assert 'path' in api
            assert 'description' in api
            assert 'parameters' in api

    @pytest.mark.asyncio
    async def test_mcp_service_apis(self, manager):
        """Test MCP service APIs"""
        apis = manager.get_apis_for_application('digital_sales_mcp')

        # Should have APIs in standardized dictionary format
        assert isinstance(apis, dict)
        assert len(apis) >= 2  # At least 2 mock APIs

        # Verify standardized format (dictionary of API definitions)
        for api_name, api_info in apis.items():
            assert isinstance(api_info, dict)
            assert 'app_name' in api_info
            assert 'api_name' in api_info
            assert 'description' in api_info
            assert 'parameters' in api_info
            assert 'path' in api_info
            assert 'method' in api_info

    @pytest.mark.asyncio
    async def test_call_legacy_function(self, manager):
        """Test calling legacy service function"""
        # Find a tool from the legacy service dynamically
        apis = manager.get_apis_for_application('digital_sales_legacy')
        assert isinstance(apis, dict) and len(apis) > 0

        # Find a tool that likely has no required parameters (like get_my_accounts)
        tool_name = None
        for api_name, api_info in apis.items():
            if isinstance(api_info, dict):
                params = api_info.get('parameters', [])
                required_params = [p for p in params if isinstance(p, dict) and p.get('required', False)]
                # Prefer tools with no required params, or tools with 'account' in the name
                if not required_params or 'account' in api_name.lower():
                    tool_name = api_name
                    break

        # If no suitable tool found, use the first one
        if not tool_name:
            tool_name = list(apis.keys())[0]

        result = await manager.call_tool(tool_name, {})

        assert result is not None
        assert len(result) > 0

        content = result[0]
        assert hasattr(content, 'text')

        # Parse response
        response_data = json.loads(content.text)
        assert isinstance(response_data, dict)

    @pytest.mark.asyncio
    async def test_call_mcp_function(self, manager):
        """Test calling MCP service function"""
        # Find a function with no required parameters
        apis = manager.get_apis_for_application('digital_sales_mcp')

        # APIs now returns a dictionary of API definitions
        assert isinstance(apis, dict)

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

        result = await manager.call_tool(simple_function, {})

        assert result is not None
        assert len(result) > 0

        content = result[0]
        assert hasattr(content, 'text')

    @pytest.mark.asyncio
    async def test_tool_prefixing(self, manager):
        """Test that tools are properly prefixed with service names"""
        # Get all tools from both services
        legacy_apis = manager.get_apis_for_application('digital_sales_legacy')
        mcp_apis = manager.get_apis_for_application('digital_sales_mcp')

        # Check legacy service tool names
        if isinstance(legacy_apis, dict):
            for api_name in legacy_apis.keys():
                assert api_name.startswith('digital_sales_legacy_')

        # Check MCP service tool names
        if isinstance(mcp_apis, dict):
            for api_name in mcp_apis.keys():
                assert api_name.startswith('digital_sales_mcp_')


async def run_mixed_tests():
    """Run mixed configuration tests standalone"""
    print("🧪 Testing Mixed Configuration Support")
    print("=" * 60)

    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(MIXED_CONFIG)
        temp_config_path = f.name

    try:
        # Load mixed configuration
        configs = load_service_configs(temp_config_path)
        print(f"✅ Loaded {len(configs)} service configurations")

        # Show loaded services
        for name, config in configs.items():
            print(f"   📋 {name}: {config.type} at {config.url}")

        # Initialize MCP Manager
        manager = MCPManager(configs)

        # Load tools
        print("\n🔧 Loading tools from mixed configuration...")
        await manager.load_tools()
        print("✅ Tools loaded successfully")

        # Test 1: List Applications
        print("\n📱 Test 1: List Applications")
        applications = manager.get_server_names()
        print(f"✅ Found {len(applications)} applications: {applications}")

        # Test 2: Check Legacy Service
        if 'digital_sales_legacy' in applications:
            print("\n🔍 Test 2: Legacy Service APIs")
            apis = manager.get_apis_for_application('digital_sales_legacy')
            print(f"✅ Legacy service has {len(apis)} APIs")

            # Show sample API
            if isinstance(apis, dict):
                sample_api = list(apis.values())[0]
                print(
                    f"   Sample: {sample_api.get('api_name', 'unknown')} ({sample_api.get('method', 'unknown')})"
                )

        # Test 3: Check MCP Service
        mcp_app = None
        for app in applications:
            if app in manager.mcp_clients:
                mcp_app = app
                break

        if mcp_app:
            print("\n🔍 Test 3: MCP Service APIs")
            apis = manager.get_apis_for_application(mcp_app)
            print(f"✅ MCP service has {len(apis)} APIs")

            # Show sample API
            if apis and isinstance(apis[0], dict) and 'function' in apis[0]:
                sample_api = apis[0]['function']
                print(f"   Sample: {sample_api.get('name', 'unknown')}")

        # Test 4: Call functions from both services
        print("\n📞 Test 4: Call Functions from Both Services")

        # Call legacy function
        try:
            result = await manager.call_tool('digital_sales_legacy_get_my_accounts_my_accounts_get', {})
            print("✅ Legacy function call successful!")
            if result and len(result) > 0 and hasattr(result[0], 'text'):
                response_data = json.loads(result[0].text)
                print(f"   Legacy response keys: {list(response_data.keys())}")
        except Exception as e:
            print(f"⚠️  Legacy function call failed: {e}")

        # Call MCP function
        if mcp_app:
            try:
                # Find simple function
                apis = manager.get_apis_for_application(mcp_app)
                simple_function = None
                for api in apis:
                    if isinstance(api, dict) and 'function' in api:
                        func = api['function']
                        params = func.get('parameters', {})
                        required = params.get('required', [])
                        if not required:
                            simple_function = func['name']
                            break

                if simple_function:
                    result = await manager.call_tool(simple_function, {})
                    print("✅ MCP function call successful!")
                    if result and len(result) > 0 and hasattr(result[0], 'text'):
                        print(f"   MCP response preview: {result[0].text[:100]}...")
                else:
                    print("⚠️  No simple MCP function found to test")
            except Exception as e:
                print(f"⚠️  MCP function call failed: {e}")

        print("\n🎉 Mixed configuration test completed!")

    finally:
        # Clean up
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)


if __name__ == "__main__":
    asyncio.run(run_mixed_tests())
