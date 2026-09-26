import json
import os
from typing import Any

import yaml
from playwright.async_api import BrowserContext as BrowserExtensionAsync
from playwright.async_api import Worker

from .model import (
    _JS_CODE,
    AnalyzePageResponse,
    Response,
    StateCommand,
    StateResponse,
    TCommand,
    TResponse,
)


async def _ensure_worker(browser_context, target_extension_id: str) -> Worker:
    """
    Ensure and return the Service Worker for the specified extension.

    Args:
        browser_context: The browser context to inspect.
        target_extension_id: The ID of the extension whose Service Worker you want.

    Returns:
        The correct Service Worker instance.
    """
    # Wait for service workers if not already available
    if len(browser_context.service_workers) == 0:
        await browser_context.wait_for_event("serviceworker")

    # Filter service workers based on the target extension ID
    for worker in browser_context.service_workers:
        if target_extension_id in worker.url:
            return worker

    # If no match is found, wait for a new Service Worker matching the criteria
    return await browser_context.wait_for_event(
        "serviceworker", lambda worker: target_extension_id in worker.url
    )


async def execute_on_extension_async(
    browser_context: BrowserExtensionAsync, js_code: str, command: dict[str, Any]
) -> dict[str, Any]:
    """
    Evaluates the specified javascript code in the extension context, passing the `command` as a parameter of the evaluation, returning the response serialized as `dict`.
    """

    async def _ensure_worker() -> Worker:
        if len(browser_context.service_workers) == 0:
            return await browser_context.wait_for_event("serviceworker")
        else:
            return browser_context.service_workers[0]

    worker = await _ensure_worker()
    response = await worker.evaluate(js_code, json.dumps(command))
    json_data = json.loads(response)
    return json_data


async def execute_command_sync(
    browser_context: BrowserExtensionAsync, command: TCommand, responseType: type[TResponse]
) -> TResponse:
    json_data = await execute_on_extension_async(
        browser_context, js_code=_JS_CODE, command=command.model_dump()
    )
    command_response = Response[responseType](**json_data)
    return command_response.data


async def analyze_current_page_async(
    browser_context: BrowserExtensionAsync,
) -> AnalyzePageResponse:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    rules = yaml.safe_load(open(os.path.join(current_dir, 'rules.yaml')))
    response = await execute_command_sync(
        browser_context, StateCommand(timeout=10, rules=rules), StateResponse
    )
    out_map = {}
    for _, obj in response.pageAnalysis.map.items():
        if 'bid' not in obj.html.attributes.keys():
            pass
            # print("Warning: Pu Mapping for an element failed since bid wasn't found on its attribues")
        else:
            out_map[obj.html.attributes['bid']] = obj
    response.pageAnalysis.map = out_map
    return response.pageAnalysis
