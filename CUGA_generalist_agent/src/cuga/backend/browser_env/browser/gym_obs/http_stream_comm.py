import asyncio
import uuid
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class ChromeExtensionCommunicatorProtocol(Protocol):
    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...
    async def send_request(self, data: dict, timeout: Optional[float] = None) -> dict: ...
    async def send_extraction_request(
        self, request_type: str, data: Dict[str, Any] = None
    ) -> Dict[str, Any]: ...
    async def get_next_command(self) -> dict: ...
    def resolve_request(self, req_id: str, result: dict): ...
    def is_connected(self) -> bool: ...
    async def wait_for_connection(self, timeout: float = 10.0): ...
    async def ping(self) -> bool: ...
    async def extract_dom_snapshot(self, **kwargs) -> Dict[str, Any]: ...
    async def extract_accessibility_tree(self) -> Dict[str, Any]: ...
    async def extract_screenshot(self, format: str = "png", quality: int = 100) -> str: ...
    async def extract_focused_element_bid(self) -> str: ...
    async def extract_page_content(self, as_text: bool = False) -> str: ...
    async def extract_dom_tree(
        self,
        *,
        do_highlight_elements: bool = True,
        focus_highlight_index: int = -1,
        viewport_expansion: int = 0,
        debug_mode: bool = False,
    ) -> Dict[str, Any]: ...
    async def get_active_tab_url(self) -> str: ...
    async def get_active_tab_title(self) -> str: ...


class ChromeExtensionCommunicatorHTTP:
    def __init__(self):
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._pending: Dict[str, asyncio.Future] = {}
        self.request_timeout = 30

    async def __aenter__(self):
        # For compatibility with WebSocket version
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # For compatibility with WebSocket version
        pass

    async def send_request(self, data: dict, timeout: Optional[float] = None) -> dict:
        req_id = uuid.uuid4().hex
        data["request_id"] = req_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._queue.put(data)
        try:
            return await asyncio.wait_for(fut, timeout or self.request_timeout)
        finally:
            self._pending.pop(req_id, None)

    async def send_extraction_request(self, request_type: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send extraction request to Chrome extension"""
        request = {"type": request_type, "data": data or {}}

        response = await self.send_request(request)

        if response.get("type") == "error":
            raise RuntimeError(f"Extension error: {response.get('message', 'Unknown error')}")

        return response

    async def get_next_command(self) -> dict:
        return await self._queue.get()

    def resolve_request(self, req_id: str, result: dict):
        fut = self._pending.get(req_id)
        if fut and not fut.done():
            fut.set_result(result)

    def is_connected(self) -> bool:
        # For compatibility; always return True for HTTP stream
        return True

    async def wait_for_connection(self, timeout: float = 10.0):
        # For compatibility with WebSocket version; HTTP stream is always "connected"
        # Just return immediately since we don't need to wait for a connection
        pass

    async def ping(self) -> bool:
        """Ping the Chrome extension"""
        try:
            response = await self.send_request({"type": "ping"}, timeout=5.0)
            return response.get("type") == "pong"
        except Exception:
            return False

    async def extract_dom_snapshot(self, **kwargs) -> Dict[str, Any]:
        """Extract DOM snapshot"""
        response = await self.send_extraction_request("extract_dom_snapshot", kwargs)
        return response.get("data", {})

    async def extract_accessibility_tree(self) -> Dict[str, Any]:
        """Extract accessibility tree"""
        response = await self.send_extraction_request("extract_accessibility_tree")
        return response.get("data", {})

    async def extract_screenshot(self, format: str = "png", quality: int = 100) -> str:
        """Extract screenshot"""
        response = await self.send_extraction_request(
            "extract_screenshot", {"format": format, "quality": quality}
        )
        return response.get("data", "")

    async def extract_focused_element_bid(self) -> str:
        """Extract focused element BID"""
        response = await self.send_extraction_request("extract_focused_element_bid")
        return response.get("data", "")

    async def extract_page_content(self, as_text: bool = False) -> str:
        """Extract page content"""
        response = await self.send_extraction_request("extract_page_content", {"as_text": as_text})
        return response.get("data", "")

    async def extract_dom_tree(
        self,
        do_highlight_elements: bool = True,
        focus_highlight_index: int = -1,
        viewport_expansion: int = 0,
        debug_mode: bool = False,
    ) -> Dict[str, Any]:
        """Extract DOM tree with interactive element analysis"""
        response = await self.send_extraction_request(
            "extract_dom_tree",
            {
                "do_highlight_elements": do_highlight_elements,
                "focus_highlight_index": focus_highlight_index,
                "viewport_expansion": viewport_expansion,
                "debug_mode": debug_mode,
            },
        )
        return response.get("data", {})

    async def get_active_tab_url(self) -> str:
        """Get the URL of the active browser tab"""
        response = await self.send_extraction_request("get_active_tab_url")
        return response.get("data", "")

    async def get_active_tab_title(self) -> str:
        """Get the title of the active browser tab"""
        response = await self.send_extraction_request("get_active_tab_title")
        return response.get("data", "")

    async def mark_elements(self, tags_to_mark: str = "standard_html") -> list:
        """Mark DOM elements"""
        response = await self.send_extraction_request("mark_elements", {"tags_to_mark": tags_to_mark})
        return response.get("warnings", [])

    async def unmark_elements(self):
        """Unmark DOM elements"""
        await self.send_extraction_request("unmark_elements")
