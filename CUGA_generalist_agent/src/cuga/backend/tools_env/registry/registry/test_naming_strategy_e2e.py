#!/usr/bin/env python3
"""
End-to-End test for tool naming strategy.

Tests that the naming strategy correctly uses:
1. First path segment when segments are unique
2. Operation ID when first segments are not unique
"""

import os
import json
import pytest
import pytest_asyncio
import tempfile
from cuga.backend.tools_env.registry.config.config_loader import load_service_configs
from cuga.backend.tools_env.registry.mcp_manager.mcp_manager import MCPManager


# OpenAPI spec for app with NON-UNIQUE first segments (should use operation_id)
# All paths start with /users, so first segment is not unique
NON_UNIQUE_SEGMENTS_SPEC = {
    "openapi": "3.0.0",
    "info": {
        "title": "Non-Unique Segments API",
        "version": "1.0.0",
        "description": "API where all paths share the same first segment",
    },
    "servers": [{"url": "http://localhost:8003"}],
    "paths": {
        "/users/{id}": {
            "get": {
                "operationId": "getUserById",
                "summary": "Get user by ID",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {
                        "description": "User found",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/users/list": {
            "get": {
                "operationId": "listUsers",
                "summary": "List all users",
                "responses": {
                    "200": {
                        "description": "List of users",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/users/create": {
            "post": {
                "operationId": "createUser",
                "summary": "Create a new user",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "User created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
    },
}

# OpenAPI spec for app with UNIQUE first segments (should use first segment)
# Each path has a different first segment
UNIQUE_SEGMENTS_SPEC = {
    "openapi": "3.0.0",
    "info": {
        "title": "Unique Segments API",
        "version": "1.0.0",
        "description": "API where each path has a unique first segment",
    },
    "servers": [{"url": "http://localhost:8004"}],
    "paths": {
        "/health": {
            "get": {
                "operationId": "checkHealth",
                "summary": "Health check endpoint",
                "responses": {
                    "200": {
                        "description": "Service is healthy",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"status": {"type": "string", "example": "healthy"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/status": {
            "get": {
                "operationId": "getStatus",
                "summary": "Get service status",
                "responses": {
                    "200": {
                        "description": "Service status",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                        "uptime": {"type": "number"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/metrics": {
            "get": {
                "operationId": "getMetrics",
                "summary": "Get service metrics",
                "responses": {
                    "200": {
                        "description": "Service metrics",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "requests": {"type": "number"},
                                        "errors": {"type": "number"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
    },
}


@pytest_asyncio.fixture(scope="module")
async def manager():
    """Setup MCPManager with test configuration using local OpenAPI specs"""
    # Create temporary config file with direct file paths
    config_path = None
    spec1_path = None
    spec2_path = None

    try:
        # Write OpenAPI specs to temporary files
        spec1_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(NON_UNIQUE_SEGMENTS_SPEC, spec1_file)
        spec1_file.close()
        spec1_path = spec1_file.name

        spec2_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(UNIQUE_SEGMENTS_SPEC, spec2_file)
        spec2_file.close()
        spec2_path = spec2_file.name

        # Create config file with direct file paths (not file:// URLs)
        config_content = f"""# Test configuration for naming strategy
services:
  - non_unique_segments:
      type: openapi
      url: {spec1_path}
      description: "API with non-unique first segments (should use operation_id)"
  
  - unique_segments:
      type: openapi
      url: {spec2_path}
      description: "API with unique first segments (should use first segment)"
"""

        config_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        config_file.write(config_content)
        config_file.close()
        config_path = config_file.name

        # Load configuration
        configs = load_service_configs(config_path)
        manager = MCPManager(configs)
        await manager.load_tools()

        yield manager

    finally:
        # Cleanup
        if config_path and os.path.exists(config_path):
            try:
                os.unlink(config_path)
            except Exception:
                pass
        if spec1_path and os.path.exists(spec1_path):
            try:
                os.unlink(spec1_path)
            except Exception:
                pass
        if spec2_path and os.path.exists(spec2_path):
            try:
                os.unlink(spec2_path)
            except Exception:
                pass


class TestNamingStrategyE2E:
    """End-to-End tests for tool naming strategy"""

    @pytest.mark.asyncio
    async def test_apps_loaded(self, manager):
        """Test that both test apps are loaded"""
        applications = manager.get_server_names()
        assert "non_unique_segments" in applications
        assert "unique_segments" in applications

    @pytest.mark.asyncio
    async def test_non_unique_segments_uses_operation_id(self, manager):
        """Test that app with non-unique segments uses operation_id for naming"""
        apis = manager.get_apis_for_application("non_unique_segments")
        assert isinstance(apis, dict)
        assert len(apis) == 3

        # All paths start with /users, so first segment is not unique
        # Should use operation_id: getUserById, listUsers, createUser
        function_names = list(apis.keys())

        # Check that function names contain operation_id (not just "users")
        assert any(
            "getuserbyid" in name.lower() or "get_user_by_id" in name.lower() for name in function_names
        ), f"Expected operation_id in names, got: {function_names}"
        assert any("listusers" in name.lower() or "list_users" in name.lower() for name in function_names), (
            f"Expected operation_id in names, got: {function_names}"
        )
        assert any(
            "createuser" in name.lower() or "create_user" in name.lower() for name in function_names
        ), f"Expected operation_id in names, got: {function_names}"

        # Verify all names start with app prefix
        for name in function_names:
            assert name.startswith("non_unique_segments_"), (
                f"Function name {name} should start with app prefix"
            )

    @pytest.mark.asyncio
    async def test_unique_segments_uses_first_segment(self, manager):
        """Test that app with unique segments uses first segment for naming"""
        apis = manager.get_apis_for_application("unique_segments")
        assert isinstance(apis, dict)
        assert len(apis) == 3

        # Each path has unique first segment: /health, /status, /metrics
        # Should use first segment: health, status, metrics
        function_names = list(apis.keys())

        # Check that function names contain first segment (not operation_id)
        assert any("health" in name.lower() for name in function_names), (
            f"Expected 'health' in names, got: {function_names}"
        )
        assert any("status" in name.lower() for name in function_names), (
            f"Expected 'status' in names, got: {function_names}"
        )
        assert any("metrics" in name.lower() for name in function_names), (
            f"Expected 'metrics' in names, got: {function_names}"
        )

        # Verify all names start with app prefix
        for name in function_names:
            assert name.startswith("unique_segments_"), f"Function name {name} should start with app prefix"

        # Verify names do NOT contain operation_id
        # (operation_id would be: checkHealth, getStatus, getMetrics)
        assert not any("checkhealth" in name.lower() for name in function_names), (
            f"Should use first segment, not operation_id. Got: {function_names}"
        )
        assert not any("getstatus" in name.lower() for name in function_names), (
            f"Should use first segment, not operation_id. Got: {function_names}"
        )
        assert not any("getmetrics" in name.lower() for name in function_names), (
            f"Should use first segment, not operation_id. Got: {function_names}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
