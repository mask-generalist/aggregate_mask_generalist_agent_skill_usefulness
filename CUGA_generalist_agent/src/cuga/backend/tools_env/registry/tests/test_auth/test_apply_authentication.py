#!/usr/bin/env python3
"""
Unit tests for the apply_authentication function.
Tests various authentication types: bearer, basic, header, api-key, and query.
"""

import pytest
import base64
from cuga.backend.tools_env.registry.config.config_loader import Auth
from cuga.backend.tools_env.registry.mcp_manager.adapter import apply_authentication


class TestApplyAuthentication:
    """Unit tests for apply_authentication function"""

    def test_bearer_auth(self):
        """Test bearer token authentication"""
        auth = Auth(type='bearer', value='my-token')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert headers['Authorization'] == 'Bearer my-token'
        assert len(query_params) == 0

    def test_basic_auth_valid_format(self):
        """Test basic authentication with valid username:password format"""
        auth = Auth(type='basic', value='username:password')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        expected = base64.b64encode('username:password'.encode()).decode()
        assert headers['Authorization'] == f'Basic {expected}'
        assert len(query_params) == 0

    def test_basic_auth_invalid_format(self):
        """Test basic authentication with invalid format (missing colon)"""
        auth = Auth(type='basic', value='invalid_format')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert 'Authorization' not in headers
        assert len(query_params) == 0

    def test_header_auth_with_key(self):
        """Test custom header authentication"""
        auth = Auth(type='header', key='X-API-Key', value='my-secret-key')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert headers['X-API-Key'] == 'my-secret-key'
        assert len(query_params) == 0

    def test_header_auth_without_key(self):
        """Test header authentication without key field"""
        auth = Auth(type='header', value='my-value')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert len(query_params) == 0

    def test_api_key_auth_with_default_key(self):
        """Test API key authentication with default key name"""
        auth = Auth(type='api-key', value='my-api-key')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert query_params['api_key'] == 'my-api-key'

    def test_api_key_auth_with_custom_key(self):
        """Test API key authentication with custom key name"""
        auth = Auth(type='api-key', key='custom_key', value='my-api-key')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert query_params['custom_key'] == 'my-api-key'

    def test_query_auth_with_custom_key(self):
        """Test query parameter authentication"""
        auth = Auth(type='query', key='auth_token', value='my-token')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert query_params['auth_token'] == 'my-token'

    def test_query_auth_with_default_key(self):
        """Test query parameter authentication with default key"""
        auth = Auth(type='query', value='my-token')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert query_params['api_key'] == 'my-token'

    def test_no_auth(self):
        """Test when auth is None"""
        auth = None
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert len(query_params) == 0

    def test_auth_without_value(self):
        """Test when auth has no value"""
        auth = Auth(type='bearer', value=None)
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert len(query_params) == 0

    def test_unknown_auth_type(self):
        """Test unknown authentication type"""
        auth = Auth(type='unknown', value='some-value')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert len(headers) == 0
        assert len(query_params) == 0

    def test_preserves_existing_headers(self):
        """Test that existing headers are preserved"""
        auth = Auth(type='bearer', value='my-token')
        headers = {'Content-Type': 'application/json', 'User-Agent': 'test'}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert headers['Authorization'] == 'Bearer my-token'
        assert headers['Content-Type'] == 'application/json'
        assert headers['User-Agent'] == 'test'

    def test_preserves_existing_query_params(self):
        """Test that existing query parameters are preserved"""
        auth = Auth(type='api-key', value='my-key')
        headers = {}
        query_params = {'page': '1', 'limit': '10'}

        apply_authentication(auth, headers, query_params)

        assert query_params['api_key'] == 'my-key'
        assert query_params['page'] == '1'
        assert query_params['limit'] == '10'

    def test_case_insensitive_auth_type(self):
        """Test that auth type is case insensitive"""
        auth = Auth(type='BEARER', value='my-token')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert headers['Authorization'] == 'Bearer my-token'

    def test_bearer_with_uppercase(self):
        """Test bearer authentication with uppercase type"""
        auth = Auth(type='Bearer', value='test-token')
        headers = {}
        query_params = {}

        apply_authentication(auth, headers, query_params)

        assert headers['Authorization'] == 'Bearer test-token'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
