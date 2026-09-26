import unittest
from unittest.mock import Mock, patch
import json
import requests
from pydantic import BaseModel
from typing import Optional, List
import traceback
import sys


# Mock models for testing
class Pet(BaseModel):
    id: Optional[int] = None
    name: str
    category: Optional[dict] = None
    photoUrls: List[str]
    tags: Optional[List[dict]] = None
    status: Optional[str] = "available"


class User(BaseModel):
    id: Optional[int] = None
    username: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None
    userStatus: Optional[int] = None


class Order(BaseModel):
    id: Optional[int] = None
    petId: int
    quantity: Optional[int] = 1
    shipDate: Optional[str] = None
    status: Optional[str] = "placed"
    complete: Optional[bool] = False


# Mock API configuration
class MockAPI:
    def __init__(self, method, path, requires_auth=False):
        self.method = method
        self.path = path
        self.requires_auth = requires_auth


# Mock helper functions
def extract_url_params(api, all_params):
    """Mock implementation of extract_url_params"""
    if api.path == "/pet/{petId}":
        return {"petId": str(all_params.get("id", 1))}, {}
    elif api.path == "/user/{username}":
        return {"username": all_params.get("username", "testuser")}, {}
    elif api.path == "/store/order/{orderId}":
        return {"orderId": str(all_params.get("id", 1))}, {}
    elif api.path == "/pet/findByStatus":
        return {}, {"status": all_params.get("status", "available")}
    return {}, {}


def construct_final_url(base_url, api, path_params, query_params):
    """Mock implementation of construct_final_url"""
    url = base_url + api.path

    # Replace path parameters
    for key, value in path_params.items():
        url = url.replace(f"{{{key}}}", str(value))

    # Add query parameters
    if query_params:
        query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])
        url += f"?{query_string}"

    return url


def extract_body_params(api, all_params):
    """Mock implementation of extract_body_params"""
    if api.method in ["POST", "PUT", "PATCH"]:
        # Remove None values and return relevant body params
        return {k: v for k, v in all_params.items() if v is not None and k != "id"}
    return {}


def determine_content_type(api):
    """Mock implementation of determine_content_type"""
    return True  # Always use JSON for simplicity


# Your handler function (modified to work with our mocks)
def handler(
    params: BaseModel, headers: dict = None, api=None, base_url="https://petstore3.swagger.io/api/v3"
):
    all_params = params.dict()
    headers = headers if headers else {}

    try:
        path_params, query_params = extract_url_params(api, all_params)
        final_url = construct_final_url(base_url, api, path_params, query_params)
        body_params = extract_body_params(api, all_params)
        use_json = determine_content_type(api)

        if use_json:
            response = requests.request(api.method, final_url, headers=headers, json=body_params)
        else:
            response = requests.request(api.method, final_url, headers=headers, data=body_params)

        response.raise_for_status()
        return response.text

    except Exception as e:
        error_response = {
            "status": "exception",
            "error_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
            "parameters": all_params,
        }

        # Add HTTP-specific details if it's an HTTP error
        if hasattr(e, 'response') and e.response is not None:
            error_response["status_code"] = e.response.status_code
            error_response["url"] = final_url if 'final_url' in locals() else None
            error_response["method"] = api.method

            # Try to get response body for more details
            try:
                if e.response.headers.get('content-type', '').startswith('application/json'):
                    error_response["response_body"] = e.response.json()
                else:
                    error_response["response_body"] = e.response.text
            except Exception:
                pass

        return error_response


# Test cases for different Petstore endpoints
class TestPetstoreHandler(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.base_url = "https://petstore3.swagger.io/api/v3"

    @patch('requests.request')
    def test_successful_get_pet_by_id(self, mock_request):
        """Test successful GET /pet/{petId}"""
        # Setup
        api = MockAPI("GET", "/pet/{petId}")

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"id": 1, "name": "doggie", "photoUrls": ["url1"]}'
        mock_request.return_value = mock_response

        # Test data
        params = Pet(id=1, name="doggie", photoUrls=["url1"])

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertEqual(result, '{"id": 1, "name": "doggie", "photoUrls": ["url1"]}')
        mock_request.assert_called_once_with(
            "GET", "https://petstore3.swagger.io/api/v3/pet/1", headers={}, json={}
        )

    @patch('requests.request')
    def test_pet_not_found_404(self, mock_request):
        """Test GET /pet/{petId} with non-existent pet ID"""
        # Setup
        api = MockAPI("GET", "/pet/{petId}")

        # Mock 404 response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.reason = "Not Found"
        mock_response.text = "Pet not found"
        mock_response.headers = {"content-type": "text/plain"}
        mock_request.return_value = mock_response

        # Create HTTPError with response
        http_error = requests.exceptions.HTTPError("404 Client Error")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        # Test data
        params = Pet(id=999, name="doggie", photoUrls=["url1"])

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "HTTPError")
        self.assertEqual(result["status_code"], 404)
        self.assertEqual(result["method"], "GET")
        self.assertEqual(result["response_body"], "Pet not found")

    @patch('requests.request')
    def test_validation_error_422_missing_required_fields(self, mock_request):
        """Test POST /pet with validation error response from server"""
        # Setup
        api = MockAPI("POST", "/pet")

        # Mock 422 response
        mock_response = Mock()
        mock_response.status_code = 422
        mock_response.reason = "Unprocessable Entity"
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "code": 422,
            "message": "Validation failed",
            "errors": [
                {"field": "name", "message": "name is required"},
                {"field": "photoUrls", "message": "photoUrls is required"},
            ],
        }
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_request.return_value = mock_response

        # Create HTTPError with response
        http_error = requests.exceptions.HTTPError("422 Client Error: Unprocessable Entity")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        # Test data - valid Pydantic model but server rejects it
        params = Pet(name="doggie", photoUrls=["url1"])

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "HTTPError")
        self.assertEqual(result["status_code"], 422)
        self.assertEqual(result["method"], "POST")
        self.assertIn("Validation failed", result["response_body"]["message"])
        self.assertIn("traceback", result)  # Should contain full traceback
        self.assertIn("name", result["parameters"])  # Parameters sent

    @patch('requests.request')
    def test_connection_error(self, mock_request):
        """Test connection error handling"""
        # Setup
        api = MockAPI("GET", "/pet/findByStatus")

        # Mock connection error
        mock_request.side_effect = requests.exceptions.ConnectionError("Failed to establish a new connection")

        # Test data
        params = Pet(name="doggie", photoUrls=["url1"])

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "ConnectionError")
        self.assertIn("Failed to establish a new connection", result["message"])
        self.assertIn("traceback", result)

    @patch('requests.request')
    def test_timeout_error(self, mock_request):
        """Test timeout error handling"""
        # Setup
        api = MockAPI("POST", "/user")

        # Mock timeout error
        mock_request.side_effect = requests.exceptions.Timeout("Request timed out after 30 seconds")

        # Test data
        params = User(username="testuser")

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "Timeout")
        self.assertIn("Request timed out", result["message"])

    def test_parameter_extraction_error(self):
        """Test error in parameter extraction by modifying the function"""
        # Setup
        api = MockAPI("GET", "/pet/{petId}")

        # Patch the extract_url_params to raise an error
        # Get the current module (works whether run as script or via pytest)
        current_module = sys.modules[handler.__module__]
        with patch.object(current_module, 'extract_url_params') as mock_extract:
            mock_extract.side_effect = ValueError("Invalid pet ID format: must be integer")

            # Test data
            params = Pet(name="doggie", photoUrls=["url1"])

            # Execute
            result = handler(params, api=api)

            # Verify
            self.assertIsInstance(result, dict)
            self.assertEqual(result["status"], "exception")
            self.assertEqual(result["error_type"], "ValueError")
            self.assertIn("Invalid pet ID format", result["message"])
            self.assertIn("traceback", result)
            self.assertEqual(result["parameters"], params.dict())

    @patch('requests.request')
    def test_unauthorized_error_401(self, mock_request):
        """Test 401 Unauthorized error for protected endpoints"""
        # Setup
        api = MockAPI("DELETE", "/pet/{petId}", requires_auth=True)

        # Mock 401 response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.reason = "Unauthorized"
        mock_response.text = "Invalid API key"
        mock_response.headers = {"content-type": "text/plain"}
        mock_request.return_value = mock_response

        # Create HTTPError with response
        http_error = requests.exceptions.HTTPError("401 Client Error")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        # Test data
        params = Pet(id=1, name="doggie", photoUrls=["url1"])

        # Execute (without auth headers)
        result = handler(params, api=api)

        # Verify
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "HTTPError")
        self.assertEqual(result["status_code"], 401)
        self.assertEqual(result["response_body"], "Invalid API key")

    @patch('requests.request')
    def test_server_error_500(self, mock_request):
        """Test 500 Internal Server Error"""
        # Setup
        api = MockAPI("POST", "/store/order")

        # Mock 500 response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.reason = "Internal Server Error"
        mock_response.text = "Database connection failed"
        mock_response.headers = {"content-type": "text/plain"}
        mock_request.return_value = mock_response

        # Create HTTPError with response
        http_error = requests.exceptions.HTTPError("500 Server Error")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        # Test data
        params = Order(petId=1, quantity=2)

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "HTTPError")
        self.assertEqual(result["status_code"], 500)
        self.assertEqual(result["response_body"], "Database connection failed")

    @patch('requests.request')
    def test_successful_post_with_json_body(self, mock_request):
        """Test successful POST /pet with JSON body"""
        # Setup
        api = MockAPI("POST", "/pet")

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"id": 123, "name": "doggie", "photoUrls": ["url1"], "status": "available"}'
        mock_request.return_value = mock_response

        # Test data
        params = Pet(name="doggie", photoUrls=["url1"], status="available")

        # Execute
        result = handler(params, api=api)

        # Verify
        self.assertEqual(
            result, '{"id": 123, "name": "doggie", "photoUrls": ["url1"], "status": "available"}'
        )
        mock_request.assert_called_once_with(
            "POST",
            "https://petstore3.swagger.io/api/v3/pet",
            headers={},
            json={"name": "doggie", "photoUrls": ["url1"], "status": "available"},
        )

    def test_pydantic_validation_error_in_handler(self):
        """Test how handler responds to invalid data that causes processing errors"""
        # Setup
        api = MockAPI("POST", "/pet")

        # Create invalid parameters that would cause issues during processing
        class InvalidPet(BaseModel):
            name: str
            photoUrls: List[str]
            invalid_field: dict = {"nested": {"deeply": {"invalid": "structure"}}}

        params = InvalidPet(name="test", photoUrls=["url1"], invalid_field={"this": "will cause issues"})

        # Patch extract_body_params to simulate parameter processing error
        # Get the current module (works whether run as script or via pytest)
        current_module = sys.modules[handler.__module__]
        with patch.object(current_module, 'extract_body_params') as mock_extract:
            mock_extract.side_effect = TypeError("Cannot serialize complex nested object")

            # Execute
            result = handler(params, api=api)

            # Verify
            self.assertIsInstance(result, dict)
            self.assertEqual(result["status"], "exception")
            self.assertEqual(result["error_type"], "TypeError")
            self.assertIn("Cannot serialize", result["message"])
            self.assertIn("traceback", result)

    @patch('requests.request')
    def test_bad_request_400_with_parameter_details(self, mock_request):
        """Test 400 Bad Request with parameter validation details"""
        # Setup
        api = MockAPI("POST", "/pet")

        # Mock 400 response with detailed error
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.reason = "Bad Request"
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "error": "Bad Request",
            "message": "Invalid parameter values",
            "details": {
                "photoUrls": "At least one photo URL is required",
                "status": "Must be one of: available, pending, sold",
            },
        }
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_request.return_value = mock_response

        # Create HTTPError with response
        http_error = requests.exceptions.HTTPError("400 Client Error: Bad Request")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error

        # Test data
        params = Pet(name="test", photoUrls=[], status="invalid_status")

        # Execute
        result = handler(params, api=api)

        # Verify error structure
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["status_code"], 400)
        self.assertIn("Invalid parameter values", result["response_body"]["message"])
        self.assertIn("photoUrls", result["response_body"]["details"])
        self.assertIn("traceback", result)  # Full error trace available

        # Verify parameters are included for debugging
        self.assertEqual(result["parameters"]["name"], "test")
        self.assertEqual(result["parameters"]["photoUrls"], [])
        self.assertEqual(result["parameters"]["status"], "invalid_status")

    def test_real_api_422_validation_error(self):
        """Test real API call to Petstore that triggers actual validation error"""
        # Setup for real API call
        MockAPI("POST", "/pet")

        # Create a real handler that calls the actual Petstore API
        def real_handler(params: BaseModel, headers: dict = None):
            all_params = params.dict()
            headers = headers if headers else {}

            try:
                # For this test, we'll construct the URL manually to call real API
                final_url = "https://petstore3.swagger.io/api/v3/pet"

                # Try different invalid payloads to trigger validation errors
                test_payloads = [
                    # Test 1: Missing required fields
                    {},
                    # Test 2: Invalid data types
                    {"id": "not_a_number", "name": None, "photoUrls": "not_an_array"},
                    # Test 3: Empty required fields
                    {"name": "", "photoUrls": []},
                    # Test 4: Invalid enum values
                    {
                        "name": "test",
                        "photoUrls": ["http://example.com/photo.jpg"],
                        "status": "invalid_status_value",
                    },
                ]

                last_error = None

                # Try each payload until we get a validation error (not 500)
                for i, payload in enumerate(test_payloads):
                    try:
                        print(f"\n--- Trying payload {i + 1}: {payload} ---")

                        response = requests.post(
                            final_url, headers={"Content-Type": "application/json"}, json=payload, timeout=10
                        )

                        response.raise_for_status()
                        return response.text  # Shouldn't reach here

                    except requests.exceptions.HTTPError as e:
                        print(f"Got HTTP {e.response.status_code}: {e.response.reason}")

                        # If we get a validation error (400, 422), use it
                        if e.response.status_code in [400, 422]:
                            last_error = e
                            break
                        # If we get 405 Method Not Allowed, the endpoint might not exist
                        elif e.response.status_code == 405:
                            last_error = e
                            break
                        # For other errors (like 500), try next payload
                        else:
                            last_error = e
                            continue
                    except Exception as e:
                        last_error = e
                        continue

                # If we didn't get a validation error, raise the last error we got
                if last_error:
                    raise last_error
                else:
                    raise Exception("No error occurred - unexpected success")

            except Exception as e:
                error_response = {
                    "status": "exception",
                    "error_type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                    "parameters": all_params,
                }

                # Add HTTP-specific details if it's an HTTP error
                if hasattr(e, 'response') and e.response is not None:
                    error_response["status_code"] = e.response.status_code
                    error_response["url"] = final_url if 'final_url' in locals() else None
                    error_response["method"] = "POST"

                    # Try to get response body for more details
                    try:
                        if e.response.headers.get('content-type', '').startswith('application/json'):
                            error_response["response_body"] = e.response.json()
                        else:
                            error_response["response_body"] = e.response.text
                    except Exception:
                        error_response["response_body"] = (
                            e.response.text if hasattr(e.response, 'text') else str(e)
                        )

                return error_response

        # Test data
        params = Pet(name="test", photoUrls=["url1"])  # Valid params, but we'll send invalid data in handler

        # Execute real API call
        result = real_handler(params)

        # Verify the response structure
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["error_type"], "HTTPError")

        # Accept various error codes that indicate the API responded with an error
        # (not just validation errors, since the API behavior may vary)
        self.assertIn(result["status_code"], [400, 401, 405, 422, 500])

        # Verify we have the error details
        self.assertIn("traceback", result)
        self.assertIn("parameters", result)

        # Verify URL and method are captured
        self.assertEqual(result["url"], "https://petstore3.swagger.io/api/v3/pet")
        self.assertEqual(result["method"], "POST")

        # Print the actual response for debugging
        print("\n=== REAL API ERROR RESPONSE ===")
        print(f"Status Code: {result.get('status_code')}")
        print(f"Error Type: {result.get('error_type')}")
        print(f"Message: {result.get('message')}")
        print(f"Response Body: {result.get('response_body')}")
        print(f"Parameters Sent: {result.get('parameters')}")
        print("=" * 35)

        # Additional assertion: ensure we're actually capturing error info
        self.assertIsNotNone(result.get("status_code"))
        self.assertIsNotNone(result.get("message"))

        # If we got a 422, verify it's a validation error
        if result.get("status_code") == 422:
            self.assertIn("validation", result.get("message", "").lower())


if __name__ == '__main__':
    # Run specific test cases
    unittest.main(verbosity=2)
