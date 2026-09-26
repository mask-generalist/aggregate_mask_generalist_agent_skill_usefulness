# Authentication Tests

This directory contains comprehensive tests for OpenAPI authentication in CUGA Agent's direct server integration.

## Test Structure

### Files

1. **`auth_server.py`** - Lightweight FastAPI test server
   - Implements multiple authentication methods
   - Runs on `http://localhost:8002`
   - Supports: header, bearer, api-key, basic, and query authentication

2. **`mcp_servers_auth_test.yaml`** - Test configuration
   - Defines 5 test services, each with different auth methods
   - Used by the registry server during tests

3. **`test_apply_authentication.py`** - Unit tests
   - Tests the `apply_authentication` function in isolation
   - Covers all authentication types and edge cases
   - Fast execution, no server dependencies

4. **`test_auth_e2e.py`** - End-to-End tests
   - Tests the full authentication flow
   - Starts both auth_server and registry_server
   - Verifies authentication works through the complete stack

## Authentication Types Tested

1. **Header Authentication** (`type: header`)
   - Custom header (e.g., `X-API-Key`)
   - Config: `auth: { type: header, key: X-API-Key, value: test-secret-key }`

2. **Bearer Token** (`type: bearer`)
   - Standard OAuth2 bearer token
   - Config: `auth: { type: bearer, value: test-bearer-token }`

3. **API Key Query Parameter** (`type: api-key`)
   - API key in URL query string
   - Config: `auth: { type: api-key, key: api_key, value: test-secret-key }`

4. **Basic Authentication** (`type: basic`)
   - HTTP Basic Auth (username:password)
   - Config: `auth: { type: basic, value: testuser:testpass }`

5. **Custom Query Parameter** (`type: query`)
   - Custom query parameter name
   - Config: `auth: { type: query, key: auth_token, value: test-secret-key }`

## Running Tests

### Run All Tests
```bash
# From the repository root
uv run pytest src/cuga/backend/tools_env/registry/tests/test_auth/ -v
```

### Run Unit Tests Only
```bash
uv run pytest src/cuga/backend/tools_env/registry/tests/test_auth/test_apply_authentication.py -v
```

### Run E2E Tests Only
```bash
uv run pytest src/cuga/backend/tools_env/registry/tests/test_auth/test_auth_e2e.py -v
```

### Run E2E Tests Standalone
```bash
uv run python src/cuga/backend/tools_env/registry/tests/test_auth/test_auth_e2e.py
```

### Run Auth Server Manually
```bash
uv run python src/cuga/backend/tools_env/registry/tests/test_auth/auth_server.py
```

## Test Coverage

### Unit Tests (`test_apply_authentication.py`)
- ✅ Bearer token authentication
- ✅ Basic authentication (valid and invalid formats)
- ✅ Custom header authentication
- ✅ API key authentication (default and custom keys)
- ✅ Query parameter authentication
- ✅ No auth / null auth handling
- ✅ Unknown auth types
- ✅ Preservation of existing headers/params
- ✅ Case-insensitive auth type handling

### E2E Tests (`test_auth_e2e.py`)
- ✅ Registry loads auth configurations
- ✅ Header auth end-to-end via registry
- ✅ Bearer token auth end-to-end
- ✅ API key query parameter auth end-to-end
- ✅ Basic authentication end-to-end
- ✅ Custom query parameter auth end-to-end
- ✅ POST request with authentication (createItem)

## Architecture

```
┌──────────────────┐
│  Test Client     │
│  (httpx)         │
└────────┬─────────┘
         │ HTTP Request
         ↓
┌──────────────────┐
│ Registry Server  │ ← Reads mcp_servers_auth_test.yaml
│ (port 8001)      │   Applies auth from config
└────────┬─────────┘
         │ HTTP Request + Auth
         ↓
┌──────────────────┐
│  Auth Server     │ ← Validates authentication
│  (port 8002)     │   Returns data if valid
└──────────────────┘
```

## Key Implementation Details

1. **Authentication Application**: Auth is applied in `adapter.py:create_handler()`
   - Reads auth config from `ServiceConfig`
   - Calls `apply_authentication()` to modify headers/query params
   - Applies before making the actual HTTP request

2. **Server Startup**: E2E tests use process management
   - Cleans up any existing processes on required ports
   - Starts servers in background using subprocess
   - Waits for health checks before running tests
   - Properly terminates servers in cleanup

3. **Test Isolation**: Each auth type has its own service config
   - Prevents cross-contamination
   - Allows parallel testing
   - Clear separation of concerns

## Troubleshooting

### Port Already in Use
If tests fail due to port conflicts:
```bash
# Kill processes on ports 8001 and 8002
lsof -ti:8001 | xargs kill -9
lsof -ti:8002 | xargs kill -9
```

### Server Not Starting
- Check if required dependencies are installed: `uv sync`
- Verify the auth_server script is executable
- Check for firewall blocking localhost connections

### Tests Timing Out
- Increase timeout values in test fixtures
- Check server logs for startup issues
- Ensure no network connectivity issues

## Future Enhancements

- [ ] Add OAuth2 flow tests
- [ ] Test token refresh mechanisms
- [ ] Add tests for auth error handling
- [ ] Test rate limiting with auth
- [ ] Add integration with real auth providers

