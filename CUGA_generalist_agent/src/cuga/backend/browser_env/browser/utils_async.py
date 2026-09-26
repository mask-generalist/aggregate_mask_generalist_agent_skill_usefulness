# Copyright 2024 ServiceNow
# Modifications Copyright 2025 CUGA
# Licensed under the Apache License, Version 2.0

import playwright.async_api

_PLAYWRIGHT = None


def _set_global_playwright_async(pw: playwright.async_api.Playwright):
    global _PLAYWRIGHT
    _PLAYWRIGHT = pw


async def _get_global_playwright_async():
    global _PLAYWRIGHT
    if not _PLAYWRIGHT:
        pw = await playwright.async_api.async_playwright().start()
        _set_global_playwright_async(pw)

    return _PLAYWRIGHT
