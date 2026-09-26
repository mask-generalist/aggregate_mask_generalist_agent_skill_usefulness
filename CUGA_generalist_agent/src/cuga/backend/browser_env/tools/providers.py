"""
Providers that expose concrete implementations for browser tools.

This module defines a protocol and two implementations that return a mapping
from tool names to their underlying callables. The concrete callables are
implemented in `extension_commands.py` (when the Chrome extension is used) and
`playwright_commands.py` (when using raw Playwright without the extension).
"""

from __future__ import annotations

from typing import Callable, Dict, Protocol, Any


class BrowserToolImplProvider(Protocol):
    """Protocol for objects that provide tool implementation callables.

    The returned mapping keys are stable tool identifiers (e.g., "click",
    "type", "select_option", etc.) and values are the functions that
    implement them. The exact callable signatures may vary across
    environments (some are `async`, some may be sync), so the value type is
    expressed as `Callable[..., Any]`.
    """

    def implementations(self) -> Dict[str, Callable[..., Any]]:
        """Return a mapping from tool name to implementation callable."""
        ...


class ExtensionToolImplProvider(BrowserToolImplProvider):
    """Provider that returns implementations backed by the Chrome extension."""

    def implementations(self) -> Dict[str, Callable[..., Any]]:
        from . import extension_commands as ext

        return {
            "click": ext.click_impl,
            "type": ext.type_impl,
            "select_option": ext.select_option_impl,
            "open_app": ext.open_app_impl,
            "open_dropdown": ext.open_dropdown_impl,
            "go_back": ext.go_back_impl,
        }


class PlaywrightToolImplProvider(BrowserToolImplProvider):
    """Provider that returns implementations backed by Playwright helpers."""

    def implementations(self) -> Dict[str, Callable[..., Any]]:
        from . import playwright_commands as pw

        return {
            "click": pw.click_impl,
            "type": pw.type_impl,
            "select_option": pw.select_option_impl,
            "open_app": pw.open_app_impl,
            "open_dropdown": pw.open_dropdown_impl,
            "go_back": pw.go_back_impl,
        }


def get_default_provider(use_extension: bool) -> BrowserToolImplProvider:
    """Helper to choose the appropriate provider based on environment flag."""
    return ExtensionToolImplProvider() if use_extension else PlaywrightToolImplProvider()
