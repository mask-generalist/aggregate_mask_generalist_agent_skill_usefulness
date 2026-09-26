#!/usr/bin/env python3
"""
Test suite for Legacy OpenAPI service integration
Tests listing applications, APIs, and calling functions
"""

import asyncio
import os
import json
import pytest
import pytest_asyncio

from cuga.config import PACKAGE_ROOT
from cuga.backend.tools_env.registry.config.config_loader import load_service_configs
from cuga.backend.tools_env.registry.mcp_manager.mcp_manager import MCPManager


class TestLegacyOpenAPI:
    """Test suite for Legacy OpenAPI service integration"""

    @pytest_asyncio.fixture
    async def manager(self):
        """Setup MCPManager with legacy OpenAPI configuration"""
        config_path = os.path.join(
            PACKAGE_ROOT, "./backend/tools_env/registry/tests/config/mcp_servers_test.yaml"
        )
        configs = load_service_configs(config_path)
        manager = MCPManager(configs)
        await manager.load_tools()
        return manager

    @pytest.mark.asyncio
    async def test_list_applications(self, manager):
        """Test listing applications"""
        applications = manager.get_server_names()
        assert len(applications) > 0
        assert 'digital_sales' in applications

    @pytest.mark.asyncio
    async def test_list_apis(self, manager):
        """Test listing APIs for digital_sales"""
        apis = manager.get_apis_for_application('digital_sales')
        assert len(apis) == 4

        # Verify API structure
        api_list = list(apis.values()) if isinstance(apis, dict) else apis
        for api in api_list:
            assert isinstance(api, dict)
            assert 'api_name' in api
            assert 'method' in api
            assert 'path' in api
            assert 'description' in api
            assert 'parameters' in api

    @pytest.mark.asyncio
    async def test_call_function_no_params(self, manager):
        """Test calling a function with no parameters"""
        result = await manager.call_tool('digital_sales_my_accounts', {})

        assert result is not None
        assert len(result) > 0

        content = result[0]
        assert hasattr(content, 'text')

        # Parse response
        response_data = json.loads(content.text)
        assert isinstance(response_data, dict)
        assert 'accounts' in response_data
        assert 'coverage_id' in response_data
        assert 'client_status' in response_data

        # Verify accounts data
        accounts = response_data['accounts']
        assert isinstance(accounts, list)
        assert len(accounts) > 0

        # Check account structure
        account = accounts[0]
        assert 'name' in account
        assert 'state' in account
        assert 'revenue' in account

    @pytest.mark.asyncio
    async def test_load_openapi_spec_with_nested_body(self, manager):
        """Test loading a schema with nested parameters in body"""
        result = manager.get_apis_for_application("openapi_nested_body")

        assert result is not None
        assert 'openapi_nested_body_users' in result
        endpoint = result['openapi_nested_body_users']
        parameters = endpoint['parameters']
        assert parameters[0]['type'] == 'string'
        assert parameters[1]['type'] == 'string'
        assert parameters[2]['type'] == 'object'
        object_param = parameters[2]
        assert 'schema' in object_param
        schema = object_param['schema']
        assert schema['firstName'] == 'string'
        assert type(schema['address']) is dict
        assert schema['address']['street'] == 'string'


async def run_legacy_tests():
    """Run legacy OpenAPI tests standalone"""
    print("🧪 Testing Legacy OpenAPI Service Integration")
    print("=" * 60)

    # Load configuration with only legacy services
    config_path = "./backend/tools_env/registry/config/mcp_servers.yaml"
    configs = load_service_configs(config_path)
    print(f"✅ Loaded {len(configs)} service configurations")

    # Show loaded services
    for name, config in configs.items():
        print(f"   📋 {name}: {config.type} at {config.url}")

    # Initialize MCP Manager
    manager = MCPManager(configs)

    # Load tools
    print("\n🔧 Loading tools...")
    await manager.load_tools()
    print("✅ Tools loaded successfully")

    # Test 1: List Applications
    print("\n📱 Test 1: List Applications")
    applications = manager.get_server_names()
    print(f"✅ Found {len(applications)} applications: {applications}")

    # Test 2: List APIs for digital_sales
    if 'digital_sales' in applications:
        print("\n🔍 Test 2: List APIs for digital_sales")
        apis = manager.get_apis_for_application('digital_sales')
        print(f"✅ Found {len(apis)} APIs")

        # Show API details
        api_list = list(apis.values()) if isinstance(apis, dict) else apis
        for i, api in enumerate(api_list[:3], 1):  # Show first 3
            if isinstance(api, dict):
                name = api.get('api_name', 'unknown')
                method = api.get('method', 'unknown')
                path = api.get('path', 'unknown')
                desc = api.get('description', 'no description')
                params = api.get('parameters', [])

                print(f"   {i}. {name}")
                print(f"      Method: {method} {path}")
                print(f"      Description: {desc[:80]}{'...' if len(desc) > 80 else ''}")
                print(f"      Parameters: {len(params)} params")

                # Show parameter details
                if params:
                    for param in params[:2]:  # Show first 2 params
                        print(
                            f"        - {param.get('name', 'unknown')} ({param.get('type', 'unknown')}) {'[required]' if param.get('required') else '[optional]'}"
                        )

        # Test 3: Call a function
        print("\n📞 Test 3: Call Function - get_my_accounts")
        try:
            # Call the simplest function (no parameters required)
            result = await manager.call_tool('digital_sales_my_accounts', {})
            print("✅ Function call successful!")

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
                            if 'accounts' in response_data:
                                accounts = response_data['accounts']
                                print(
                                    f"   Found {len(accounts) if isinstance(accounts, list) else 'unknown'} accounts"
                                )
                    except Exception:
                        pass  # Not JSON, that's fine
                else:
                    print(f"   Raw result: {content}")
            else:
                print(f"   Result: {result}")

        except Exception as e:
            print(f"❌ Function call failed: {e}")
            import traceback

            traceback.print_exc()

    else:
        print("❌ digital_sales application not found")

    print("\n🎉 Legacy OpenAPI test completed!")


if __name__ == "__main__":
    asyncio.run(run_legacy_tests())
