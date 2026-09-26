"""
Extension-based implementations of browser interaction commands.

These helpers are invoked when the Chrome extension is enabled (settings.advanced_features.use_extension == True).
They wrap lower-level helpers such as `_send_browser_command` and element-lookup utilities so the public
`@tool` functions in `tools.py` can simply delegate to them.
"""

from typing import Any, Dict, List, Literal, Optional

from langchain_core.runnables import RunnableConfig
from loguru import logger

from cuga.backend.browser_env.page_understanding.types.dom_tree_types import (
    DomTreeResult,
    NodeData,
    TextNodeData,
)
from cuga.backend.cuga_graph.nodes.browser.action_agent.tools.alert import Alert

IDENTIFIER_ELEMENT = "dom-tree-id"


def _get_communicator(config: RunnableConfig | None) -> Any | None:
    """Retrieve the ChromeExtensionCommunicator instance.

    Preference order:
    1. Provided via the tool's RunnableConfig under ``configurable.communicator``.
    2. From page_data in configurable if available.
    3. Global FastAPI app instance created in ``server.main`` (``app.state.chrome_extension_communicator``).
    4. Return ``None`` if no communicator can be found.
    """
    # 1) Try config
    if config and (comm := config.get("configurable", {}).get("communicator")):
        return comm

    # 2) Try page_data in configurable
    if config and (page_data := config.get("configurable", {}).get("page_data")):
        if isinstance(page_data, dict) and "chrome_extension_communicator" in page_data:
            return page_data["chrome_extension_communicator"]

    # 3) Try to import the running FastAPI app created in server.main
    try:
        from server.main import app  # type: ignore

        comm = getattr(app.state, "chrome_extension_communicator", None)
        if comm:
            return comm
    except Exception:
        pass

    return None


async def _send_browser_command(command: str, args: Dict[str, Any], config: RunnableConfig | None):
    """Send a browser command to the Chrome extension via WebSocket or HTTP stream.

    This is a *best-effort* operation: if no communicator is available we simply log and exit so
    the agent can continue operating without throwing errors.
    """
    communicator = _get_communicator(config)

    if communicator is None:
        logger.warning(
            f"[tools.py] No ChromeExtensionCommunicator available – cannot send command '{command}'."
        )
        return None

    try:
        msg = {"type": "browser_command", "command": command, "args": args}

        # Handle different communicator types
        if hasattr(communicator, 'server'):
            # WebSocket communicator
            response = await communicator.server.send_request(msg, timeout=10.0)
        else:
            # HTTP stream communicator
            response = await communicator.send_request(msg, timeout=10.0)

        logger.debug(f"[tools.py] Sent browser_command: {msg}")
        logger.debug(f"[tools.py] Received response: {response}")

        if response and response.get("type") == "error":
            logger.error(f"[tools.py] Browser command '{command}' failed: {response.get('message')}")
            return None

        return response

    except Exception as e:
        logger.error(f"[tools.py] Failed to send browser command '{command}': {e}")
        return None


async def _add_animation(
    bid: str,
    icon_type: str,
    banner_text: str,
    config: RunnableConfig | None = None,
):
    """
    Add a visual animation to the element with the given BID.
    Args:
        bid: The browsergym ID of the element
        icon_type: Type of icon to display (e.g., "typing", "loading", "success")
        banner_text: Text to display in the banner
    """
    response = await _send_browser_command(
        "add_animation",
        {"bid": bid, "icon_type": icon_type, "banner_text": banner_text},
        config,
    )
    return response


def _get_page_data(config: RunnableConfig | None) -> Optional[Dict[str, Any]]:
    """Retrieve page data from the config.

    Returns:
        Dict containing page data (dom_object, accessibility_tree, extra_properties, etc.) or None
    """
    if not config:
        return None

    # Try to get from configurable.page_data
    page_data = config.get("configurable", {}).get("page_data")
    if page_data:
        return page_data

    return None


def _get_dom_tree(config: RunnableConfig | None):
    """Retrieve the DOM tree from page data.

    Returns:
        DomTreeResult object or None if not found
    """
    page_data = _get_page_data(config)
    if not page_data:
        return None

    return page_data.get("dom_tree")


def get_node_by_dom_tree_id(dom_tree_id: int, dom_tree: DomTreeResult) -> NodeData | TextNodeData | None:
    # Traverse all nodes to find matching DOM Tree ID
    target_node = None
    for node in dom_tree.map.values():
        if isinstance(node, NodeData) and node.dom_tree_id == dom_tree_id:
            target_node = node
            break

    if not target_node:
        logger.warning(f"No element found with dom_tree_id #{dom_tree_id} in DOM tree")

    return target_node


def _find_browsergym_id_in_children(
    element: NodeData, dom_tree: DomTreeResult, max_depth: int = 2
) -> str | None:
    """
    Search for IDENTIFIER_ELEMENT attribute in element's children up to max_depth levels.

    Args:
        element: The DOM element to search in
        dom_tree: The DomTreeResult to get child nodes from
        max_depth: Maximum depth to search (default 2)

    Returns:
        The browsergym ID if found, None otherwise
    """

    def search_recursive(node: NodeData, current_depth: int) -> str | None:
        if current_depth > max_depth:
            return None

        # Check if this node has the IDENTIFIER_ELEMENT
        if hasattr(node, 'attributes') and node.attributes:
            browsergym_id = node.attributes.get(IDENTIFIER_ELEMENT)
            if browsergym_id:
                return browsergym_id

        # Search children if we haven't reached max depth
        if current_depth < max_depth and hasattr(node, 'children') and node.children:
            for child_id in node.children:
                child_node = dom_tree.get_node(child_id)
                if child_node and isinstance(child_node, NodeData):  # Skip text nodes
                    result = search_recursive(child_node, current_depth + 1)
                    if result:
                        return result

        return None

    return search_recursive(element, 0)


def get_element_name_by_bid(bid: str, page_data: dict) -> str | None:
    """Get element name/description by BID from accessibility tree.

    Args:
        bid: The browsergym ID of the element
        page_data: Page data containing accessibility_tree

    Returns:
        Element name/description or None if not found
    """
    if not page_data or not bid:
        return None

    accessibility_tree = page_data.get("axtree_object", {})
    nodes = accessibility_tree.get("nodes", [])

    for node in nodes:
        if node.get("browsergym_id") == bid:
            # Try to get name from various accessibility properties
            name = (
                node.get("name", {}).get("value")
                or node.get("role", {}).get("value")
                or node.get("description", {}).get("value")
            )
            return name

    return None


async def _get_element_by_bid_with_validation(
    bid: str, config: RunnableConfig | None
) -> tuple[str | None, Alert | None]:
    """
    Common helper function to get and validate an element by BID.

    Args:
        bid: The dom_tree_id of the target element as string
        config: RunnableConfig containing page data

    Returns:
        Tuple of (actual_browsergym_id, error_alert_or_none)
        If successful, returns (browsergym_id, None)
        If failed, returns (None, Alert_with_error_message)
    """
    # Get page data to access element information
    dom_tree = _get_dom_tree(config)
    page_data = _get_page_data(config)

    if not dom_tree or not page_data:
        return None, Alert(message="Could not get page data or dom tree")

    try:
        dom_tree_id_int = int(bid)
    except (TypeError, ValueError):
        return None, Alert(message=f"Invalid dom_tree_id provided: {bid}")

    desired_element = get_node_by_dom_tree_id(dom_tree_id_int, dom_tree)
    logger.info(f"Found element {desired_element} on page")
    if not desired_element or isinstance(desired_element, TextNodeData):
        logger.warning(f"Element with dom_tree_id {bid} not found")
        return None, Alert(message=f"Element with dom_tree_id {bid} not found")

    # First try to get the IDENTIFIER_ELEMENT from the element itself
    desired_bid = desired_element.attributes.get(IDENTIFIER_ELEMENT)

    # If not found, search up to 2 levels down in children
    if not desired_bid:
        logger.info(f"IDENTIFIER_ELEMENT not found on element {bid}, searching children...")
        desired_bid = _find_browsergym_id_in_children(desired_element, dom_tree, max_depth=2)

    if not desired_bid:
        logger.warning(
            f"Attribute {IDENTIFIER_ELEMENT} not found in element {bid} or its children (up to 2 levels)"
        )
        return None, Alert(
            message=f"Attribute {IDENTIFIER_ELEMENT} not found in element {bid} or its children"
        )

    return desired_bid, None
    """Get the tag name for an element by BID from DOM snapshot.
    
    Args:
        bid: The browsergym ID of the element
        page_data: Page data containing dom_object
        
    Returns:
        Tag name (e.g., 'div', 'button', 'input') or None if not found
    """
    if not page_data or not bid:
        return None

    dom_object = page_data.get("dom_object", {})
    if not dom_object:
        return None

    def to_string(idx):
        if idx == -1:
            return None
        else:
            return dom_object["strings"][idx]

    # Pre-locate the bid string ID
    try:
        bid_string_id = dom_object["strings"].index("data-browsergym-id")
    except ValueError:
        return None

    # Find the node with this BID
    for document in dom_object.get("documents", []):
        backend_node_ids = document.get("nodes", {}).get("backendNodeId", [])
        node_attributes = document.get("nodes", {}).get("attributes", [])
        node_names = document.get("nodes", {}).get("nodeName", [])

        for node_idx, node_attrs in enumerate(node_attributes):
            if node_idx >= len(backend_node_ids) or node_idx >= len(node_names):
                continue

            # Check if this node has the target BID
            found_bid = None
            for i in range(0, len(node_attrs), 2):
                if i + 1 >= len(node_attrs):
                    break

                name_string_id = node_attrs[i]
                value_string_id = node_attrs[i + 1]

                if name_string_id == bid_string_id:
                    found_bid = to_string(value_string_id)
                    break

            if found_bid == bid:
                # Found the node, get its tag name
                node_name_id = node_names[node_idx]
                return to_string(node_name_id)

    return None


# ---------------------------------------------------------------------------
# Low-level helpers (extension only)
# ---------------------------------------------------------------------------


async def click_impl(
    *,
    bid: str,
    button: Literal["left", "middle", "right"] = "left",
    modifiers: Optional[List[Literal["Alt", "Control", "Meta", "Shift"]]] = None,
    config: RunnableConfig | None = None,
) -> Optional[Alert]:
    """Implementation of the *click* command when the extension is enabled."""

    modifiers = modifiers or []

    # Validate / map the provided DOM-tree id to the browsergym id that the
    # extension understands.
    desired_bid, error_alert = await _get_element_by_bid_with_validation(bid, config)
    if error_alert:
        return error_alert  # early exit

    # Visual feedback in the browser (purple glow & banner)
    try:
        await _add_animation(desired_bid, "success", "Clicked!", config)  # type: ignore
    except Exception as e:  # pragma: no cover – animation failures are non-fatal
        logger.warning(f"[extension_commands] Failed to trigger click animation: {e}")

    # Finally send command to the browser via the communicator
    response = await _send_browser_command(
        "click",
        {"bid": desired_bid, "button": button, "modifiers": modifiers},
        config,
    )

    if response and response.get("result", {}).get("success"):
        logger.info(f"Click successful on element {bid}")
        return None

    error_msg = response.get("message", "Unknown error") if response else "No response from browser"
    logger.error(f"Click failed on element {bid}: {error_msg}")
    return Alert(message=f"Click failed: {error_msg}")


async def type_impl(
    *,
    bid: str,
    value: str,
    press_enter: bool,
    config: RunnableConfig | None = None,
) -> Optional[Alert]:
    """Implementation of the *type* command when the extension is enabled."""

    desired_bid, error_alert = await _get_element_by_bid_with_validation(bid, config)
    if error_alert:
        return error_alert

    try:
        await _add_animation(desired_bid, "typing", "Typing...", config)  # type: ignore
    except Exception as e:
        logger.warning(f"[extension_commands] Failed to trigger typing animation: {e}")

    response = await _send_browser_command(
        "type",
        {"bid": desired_bid, "value": value, "press_enter": press_enter},
        config,
    )

    if response and response.get("result", {}).get("success"):
        logger.info(f"Type successful on element {bid}")
        return None

    error_msg = response.get("message", "Unknown error") if response else "No response from browser"
    logger.error(f"Type failed on element {bid}: {error_msg}")
    return Alert(message=f"Type failed: {error_msg}")


async def select_option_impl(
    *,
    bid: str,
    options: str | List[str],
    config: RunnableConfig | None = None,
) -> Optional[Alert]:
    """Implementation of *select_option* when the extension is enabled."""

    desired_bid, error_alert = await _get_element_by_bid_with_validation(bid, config)
    if error_alert:
        return error_alert

    try:
        await _add_animation(desired_bid, "success", "Selected!", config)  # type: ignore
    except Exception as e:
        logger.warning(f"[extension_commands] Failed to trigger selection animation: {e}")

    response = await _send_browser_command("select_option", {"bid": desired_bid, "options": options}, config)

    if response and response.get("result", {}).get("success"):
        logger.info(f"Select successful on element {bid}")
        return None

    error_msg = response.get("message", "Unknown error") if response else "No response from browser"
    logger.error(f"Select failed on element {bid}: {error_msg}")
    return Alert(message=f"Select failed: {error_msg}")


async def open_app_impl(*, app_name: str, config: RunnableConfig | None = None):
    """Implementation of *open_app* when the extension is enabled."""

    # Delegate actual work to the background extension via communicator.
    await _send_browser_command("open_app", {"app_name": app_name}, config)
    # Nothing to return – any error will be logged by `_send_browser_command`.
    return None


async def open_dropdown_impl(
    *,
    bid: str,
    config: RunnableConfig | None = None,
) -> Optional[Alert]:
    """Open a dropdown element using the extension’s click handler."""

    # This re-uses the click implementation but forces `button="left"` and no modifiers.
    return await click_impl(bid=bid, button="left", modifiers=[], config=config)


async def go_back_impl(config: RunnableConfig | None = None):
    """
    Go back to previous page.

    Examples:
    """
    await _send_browser_command("go_back", {}, config)
