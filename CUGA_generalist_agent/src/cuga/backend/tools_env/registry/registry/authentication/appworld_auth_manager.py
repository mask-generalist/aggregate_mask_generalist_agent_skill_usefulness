import json
import httpx
from cuga.backend.tools_env.registry.registry.authentication.base_auth_manager import BaseAuthManager
from loguru import logger
from cuga.config import settings


class TokenFetchError(Exception):
    """Exception raised when token fetching fails with detailed error information."""

    def __init__(self, message: str, status_code: int = None, response_body: dict = None, url: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.url = url
        self.detailed_message = message
        if response_body and isinstance(response_body, dict):
            if "message" in response_body:
                self.detailed_message = response_body["message"]
            elif "detail" in response_body:
                self.detailed_message = response_body["detail"]


class AppWorldAuthManager(BaseAuthManager):
    def __init__(self, base_url="http://localhost:" + str(settings.server_ports.apis_url)):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self._profile = None
        self._account_passwords = None
        self._profile_loaded = False
        self._passwords_loaded = False
        logger.debug(f"AppWorldAuthManager initialized with base_url: {self.base_url}")

    @property
    def profile(self):
        """Lazy-load the user profile when first accessed. Retries if not available."""
        # Only retry if we haven't loaded yet, or if we got None and want to retry
        # For now, we'll retry once if None was returned
        if not self._profile_loaded:
            self._profile = self._get_user_profile()
            self._profile_loaded = True
        return self._profile

    def refresh_profile(self):
        """Force refresh of the profile, useful when supervisor becomes available."""
        self._profile_loaded = False
        self._profile = None
        return self.profile

    def _try_get_profile_with_retry(self, max_retries=1):
        """Try to get profile with retries. Used when authentication is actually needed."""
        profile = self.profile
        if profile is None and max_retries > 0:
            logger.debug("Profile was None, retrying once...")
            logger.debug("This may indicate the AppWorld supervisor is not yet initialized.")
            self._profile_loaded = False
            profile = self.profile
            if profile is None:
                logger.warning(
                    "Supervisor profile still not available after retry. "
                    "The AppWorld supervisor may not be initialized. "
                    "Ensure you're using the AppWorld context manager with a valid task_id."
                )
        return profile

    def _get_user_profile(self):
        """Fetch the user profile from AppWorld supervisor."""
        url = f"{self.base_url}/supervisor/profile"
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(url)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            error_detail = {
                "status_code": e.response.status_code,
                "url": str(e.request.url),
                "method": e.request.method,
                "headers": dict(e.request.headers),
            }
            try:
                error_detail["response_body"] = e.response.json()
            except Exception:
                error_detail["response_body"] = e.response.text
            try:
                error_detail["request_body"] = e.request.content.decode() if e.request.content else None
            except Exception:
                error_detail["request_body"] = None
            logger.error(f"HTTP error fetching user profile: {error_detail}")
            response_body_str = (
                json.dumps(error_detail['response_body'], indent=2)
                if isinstance(error_detail['response_body'], dict)
                else str(error_detail['response_body'])
            )
            logger.error("HTTP error fetching user profile:")
            logger.error(f"  Status Code: {error_detail['status_code']}")
            logger.error(f"  URL: {error_detail['url']}")
            logger.error(f"  Method: {error_detail['method']}")
            logger.error(f"  Response Body:\n{response_body_str}")
            if error_detail['request_body']:
                logger.error(f"  Request Body: {error_detail['request_body']}")
            print(f"\n{'=' * 60}")
            print("HTTP ERROR: Fetching user profile failed")
            print(f"{'=' * 60}")
            print(f"Status Code: {error_detail['status_code']}")
            print(f"URL: {error_detail['url']}")
            print(f"Method: {error_detail['method']}")
            print("Response Body:")
            print(response_body_str)
            if error_detail['request_body']:
                print(f"Request Body: {error_detail['request_body']}")
            print(f"{'=' * 60}\n")
            logger.warning(
                "Supervisor profile not available yet. This is normal if AppWorld supervisor hasn't been initialized."
            )
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error fetching user profile: {e}")
            print(f"\n{'=' * 60}")
            print("REQUEST ERROR: Fetching user profile failed")
            print(f"{'=' * 60}")
            print(f"Error: {e}")
            print(f"{'=' * 60}\n")
            return None

    def _get_account_passwords(self) -> dict[str, str]:
        """Lazy-load account passwords when first accessed."""
        if not self._passwords_loaded:
            self._account_passwords = self._load_account_passwords()
            self._passwords_loaded = True
        return self._account_passwords or {}

    def refresh_passwords(self):
        """Force refresh of account passwords, useful when supervisor becomes available."""
        self._passwords_loaded = False
        self._account_passwords = None
        return self._get_account_passwords()

    def _try_get_passwords_with_retry(self, max_retries=1):
        """Try to get passwords with retries. Used when authentication is actually needed."""
        passwords = self._get_account_passwords()
        if not passwords and max_retries > 0:
            logger.debug("Passwords were empty, retrying once...")
            logger.debug("This may indicate the AppWorld supervisor is not yet initialized.")
            self._passwords_loaded = False
            passwords = self._get_account_passwords()
            if not passwords:
                logger.warning(
                    "Account passwords still not available after retry. "
                    "The AppWorld supervisor may not be initialized. "
                    "Ensure you're using the AppWorld context manager with a valid task_id."
                )
        return passwords

    def _load_account_passwords(self) -> dict[str, str]:
        """Fetch account passwords from AppWorld supervisor."""
        url = f"{self.base_url}/supervisor/account_passwords"
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(url)
                r.raise_for_status()
                return {
                    item["account_name"]: item["password"]
                    for item in r.json()
                    if item.get("account_name") and item.get("password")
                }
        except httpx.HTTPStatusError as e:
            error_detail = {
                "status_code": e.response.status_code,
                "url": str(e.request.url),
                "method": e.request.method,
                "headers": dict(e.request.headers),
            }
            try:
                error_detail["response_body"] = e.response.json()
            except Exception:
                error_detail["response_body"] = e.response.text
            try:
                error_detail["request_body"] = e.request.content.decode() if e.request.content else None
            except Exception:
                error_detail["request_body"] = None
            logger.error(f"HTTP error fetching app credentials: {error_detail}")
            response_body_str = (
                json.dumps(error_detail['response_body'], indent=2)
                if isinstance(error_detail['response_body'], dict)
                else str(error_detail['response_body'])
            )
            logger.error("HTTP error fetching app credentials:")
            logger.error(f"  Status Code: {error_detail['status_code']}")
            logger.error(f"  URL: {error_detail['url']}")
            logger.error(f"  Method: {error_detail['method']}")
            logger.error(f"  Response Body:\n{response_body_str}")
            if error_detail['request_body']:
                logger.error(f"  Request Body: {error_detail['request_body']}")
            print(f"\n{'=' * 60}")
            print("HTTP ERROR: Fetching app credentials failed")
            print(f"{'=' * 60}")
            print(f"Status Code: {error_detail['status_code']}")
            print(f"URL: {error_detail['url']}")
            print(f"Method: {error_detail['method']}")
            print("Response Body:")
            print(response_body_str)
            if error_detail['request_body']:
                print(f"Request Body: {error_detail['request_body']}")
            print(f"{'=' * 60}\n")
            logger.warning(
                "Account passwords not available yet. This is normal if AppWorld supervisor hasn't been initialized."
            )
            return {}
        except httpx.RequestError as e:
            logger.error(f"Request error fetching app credentials: {e}")
            print(f"\n{'=' * 60}")
            print("REQUEST ERROR: Fetching app credentials failed")
            print(f"{'=' * 60}")
            print(f"Error: {e}")
            print(f"{'=' * 60}\n")
            return {}

    def _get_credentials(self, app_name: str) -> str | None:
        """Get credentials for an app, lazy-loading if needed. Retries once if not available."""
        passwords = self._try_get_passwords_with_retry(max_retries=1)
        if not passwords:
            logger.warning(f"No credentials available for {app_name}. Supervisor may not be initialized yet.")
        return passwords.get(app_name) if passwords else None

    def _fetch_token(self, app_name: str, password: str) -> dict:
        """Fetch authentication token for an app."""
        logger.debug("Fetching token..")
        url = f"{self.base_url}/{app_name}/auth/token"

        # Try to get profile with retry when authentication is actually needed
        profile = self._try_get_profile_with_retry(max_retries=1)
        if not profile:
            raise ValueError(
                f"Cannot fetch token for {app_name}: Supervisor profile not available. "
                f"Make sure AppWorld supervisor is initialized by entering the AppWorld context manager "
                f"with a valid task_id before making authenticated API calls."
            )

        user_name = profile["phone_number"] if app_name == "phone" else profile["email"]
        logger.debug(f"username: {user_name}")
        logger.debug(f"password: {password}")

        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(url, data={"username": user_name, "password": password})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            error_detail = {
                "status_code": e.response.status_code,
                "url": str(e.request.url),
                "method": e.request.method,
                "headers": dict(e.request.headers),
            }
            try:
                error_detail["response_body"] = e.response.json()
            except Exception:
                error_detail["response_body"] = e.response.text
            try:
                # Get request body (form data)
                if e.request.content:
                    error_detail["request_body"] = e.request.content.decode()
                else:
                    # For form data, we need to reconstruct it
                    error_detail["request_body"] = f"username={user_name}&password=***"
            except Exception:
                error_detail["request_body"] = None

            logger.error(f"HTTP error fetching token for {app_name}: {error_detail}")
            response_body_str = (
                json.dumps(error_detail['response_body'], indent=2)
                if isinstance(error_detail['response_body'], dict)
                else str(error_detail['response_body'])
            )
            logger.error(f"HTTP error fetching token for {app_name}:")
            logger.error(f"  Status Code: {error_detail['status_code']}")
            logger.error(f"  URL: {error_detail['url']}")
            logger.error(f"  Method: {error_detail['method']}")
            logger.error(f"  Username: {user_name}")
            logger.error(f"  Response Body:\n{response_body_str}")
            if error_detail['request_body']:
                logger.error(f"  Request Body: {error_detail['request_body']}")
            logger.error(f"  Headers: {json.dumps(error_detail['headers'], indent=2)}")

            print(f"\n{'=' * 60}")
            print(f"HTTP ERROR: Fetching token for {app_name} failed")
            print(f"{'=' * 60}")
            print(f"Status Code: {error_detail['status_code']}")
            print(f"URL: {error_detail['url']}")
            print(f"Method: {error_detail['method']}")
            print(f"Username: {user_name}")
            print("Response Body:")
            print(response_body_str)
            if error_detail['request_body']:
                print(f"Request Body: {error_detail['request_body']}")
            print(f"Headers: {json.dumps(error_detail['headers'], indent=2)}")
            print(f"{'=' * 60}\n")

            # Extract detailed error message from response body
            detailed_message = f"HTTP {error_detail['status_code']} error fetching token for {app_name}"
            if isinstance(error_detail['response_body'], dict):
                if "message" in error_detail['response_body']:
                    detailed_message = error_detail['response_body']["message"]
                elif "detail" in error_detail['response_body']:
                    detailed_message = error_detail['response_body']["detail"]
                else:
                    detailed_message = json.dumps(error_detail['response_body'])
            elif isinstance(error_detail['response_body'], str):
                detailed_message = error_detail['response_body']

            # Raise custom exception with detailed error information
            raise TokenFetchError(
                message=detailed_message,
                status_code=error_detail['status_code'],
                response_body=error_detail['response_body'],
                url=error_detail['url'],
            )
        except httpx.RequestError as e:
            logger.error(f"Request error fetching token for {app_name}: {e}")
            print(f"\n{'=' * 60}")
            print(f"REQUEST ERROR: Fetching token for {app_name} failed")
            print(f"{'=' * 60}")
            print(f"Error: {e}")
            print(f"URL: {url}")
            print(f"{'=' * 60}\n")
            raise
