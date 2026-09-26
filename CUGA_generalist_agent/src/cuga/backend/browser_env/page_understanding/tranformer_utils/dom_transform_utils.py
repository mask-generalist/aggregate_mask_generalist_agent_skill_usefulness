# Copyright 2024 ServiceNow
# Modifications Copyright 2025 CUGA
# Licensed under the Apache License, Version 2.0

import ast
from ..types.dom_tree_types import DomTreeResult, NodeData, TextNodeData

IGNORED_DOM_TAGS = ["br"]

IGNORED_DOM_ATTRIBUTES = (
    "style",
    "data-testid",
    "data-reactid",
    "data-react-checksum",
)

REMOVE_ATTRIBUTES = True


def flatten_domtree_to_str(
    dom_tree: DomTreeResult,
    extra_properties: dict = None,
    with_visible: bool = False,
    with_clickable: bool = False,
    with_center_coords: bool = False,
    with_bounding_box_coords: bool = False,
    with_som: bool = False,
    skip_generic: bool = True,
    filter_visible_only: bool = False,
    filter_with_bid_only: bool = False,
    filter_som_only: bool = False,
    coord_decimals: int = 0,
    ignored_tags=IGNORED_DOM_TAGS,
    ignored_attributes=IGNORED_DOM_ATTRIBUTES,
    remove_redundant_text: bool = True,
    hide_bid_if_invisible: bool = False,
    hide_all_children: bool = False,
    hide_all_bids: bool = False,
    include_xpath: bool = False,
) -> str:
    """Formats the DOM tree into a string text similar to accessibility tree format"""

    def dfs(node_id: str, depth: int, parent_node_filtered: bool, parent_node_name: str) -> str:
        tree_str = ""
        node = dom_tree.get_node(node_id)
        if node is None:
            return tree_str

        indent = "\t" * depth
        skip_node = False  # node will not be printed, with no effect on children nodes
        filter_node = False  # node will not be printed, possibly along with its children nodes

        # Handle text nodes
        if isinstance(node, TextNodeData):
            node_text = node.text.strip()
            if not node_text:
                skip_node = True
            elif parent_node_filtered:
                skip_node = True
            elif remove_redundant_text and node_text in parent_node_name:
                skip_node = True
            elif filter_visible_only and not node.is_visible:
                skip_node = True

            if not skip_node:
                tree_str += f'{indent}text "{node_text}"'
            return tree_str

        # Handle element nodes
        elif isinstance(node, NodeData):
            node_tag = node.tag_name.lower()
            node_name = ""
            node_value = None

            # Extract name from various attributes
            if "title" in node.attributes and node.attributes["title"]:
                node_name = node.attributes["title"]
            elif "alt" in node.attributes and node.attributes["alt"]:
                node_name = node.attributes["alt"]
            elif "placeholder" in node.attributes and node.attributes["placeholder"]:
                node_name = node.attributes["placeholder"]
            elif "value" in node.attributes and node.attributes["value"]:
                node_value = node.attributes["value"]
                node_name = node_value
            elif "aria-label" in node.attributes and node.attributes["aria-label"]:
                node_name = node.attributes["aria-label"]
            elif "id" in node.attributes and node.attributes["id"]:
                node_name = node.attributes["id"]
            elif "class" in node.attributes and node.attributes["class"]:
                node_name = node.attributes["class"]

            # Check if we should skip this tag
            if node_tag in ignored_tags:
                skip_node = True

            # Extract bid (assuming it might be in attributes or highlight_index)
            bid = node.dom_tree_id if node.dom_tree_id is not None else None

            # Extract node attributes
            attributes = []
            for attr_name, attr_value in node.attributes.items():
                if attr_name in ignored_attributes or attr_value is None:
                    continue
                elif attr_name in ("required", "disabled", "checked", "selected"):
                    if attr_value == "true" or attr_value == attr_name:
                        attributes.append(attr_name)
                elif attr_name not in ("title", "alt", "placeholder", "value", "aria-label", "id", "class"):
                    # Only include non-name attributes
                    attributes.append(f"{attr_name}={repr(attr_value)}")

            # Add DOM-specific attributes
            if node.is_interactive:
                attributes.append("interactive")
            if include_xpath:
                attributes.append(f'xpath="{node.xpath}"')

            if not node.highlight_index:
                skip_node = True

            if skip_generic and node_tag == "div" and not attributes and not node_name:
                skip_node = True

            if hide_all_children and parent_node_filtered:
                skip_node = True

            # Process bid-related filtering and attributes
            filter_node, extra_attributes_to_print = _process_bid_dom(
                bid,
                node,
                extra_properties=extra_properties,
                with_visible=with_visible,
                with_clickable=with_clickable,
                with_center_coords=with_center_coords,
                with_bounding_box_coords=with_bounding_box_coords,
                with_som=with_som,
                filter_visible_only=filter_visible_only,
                filter_with_bid_only=filter_with_bid_only,
                filter_som_only=filter_som_only,
                coord_decimals=coord_decimals,
            )

            # if either is True, skip the node
            skip_node = skip_node or filter_node

            # insert extra attributes before regular attributes
            attributes = extra_attributes_to_print + attributes

            # actually print the node string
            if not skip_node:
                if not node_name:
                    node_str = f"{node_tag}"
                else:
                    node_str = f"{node_tag} {repr(node_name.strip())}"

                if not (
                    hide_all_bids
                    or bid is None
                    or (
                        hide_bid_if_invisible
                        and extra_properties
                        and extra_properties.get(bid, {}).get("visibility", 0) < 0.5
                    )
                ):
                    node_str = f"[{bid}] " + node_str

                if node_value is not None and node_value != node_name:
                    node_str += f' value={repr(node_value)}'

                if not REMOVE_ATTRIBUTES and attributes:
                    node_str += ", ".join([""] + attributes)

                tree_str += f"{indent}{node_str}"

            # Process children
            for child_id in node.children:
                if child_id == node_id:  # avoid self-reference
                    continue
                child_depth = depth if skip_node else (depth + 1)
                child_str = dfs(
                    child_id,
                    child_depth,
                    parent_node_filtered=filter_node,
                    parent_node_name=node_name,
                )
                if child_str:
                    if tree_str:
                        tree_str += "\n"
                    tree_str += child_str

        return tree_str

    tree_str = dfs(dom_tree.root_id, 0, False, "")
    return tree_str


def _process_bid_dom(
    bid,
    node: NodeData,
    extra_properties: dict = None,
    with_visible: bool = False,
    with_clickable: bool = False,
    with_center_coords: bool = False,
    with_bounding_box_coords: bool = False,
    with_som: bool = False,
    filter_visible_only: bool = False,
    filter_with_bid_only: bool = False,
    filter_som_only: bool = False,
    coord_decimals: int = 0,
):
    """
    Process extra attributes and attribute-based filters for DOM elements.

    Returns:
        A flag indicating if the element should be skipped or not (due to filters).
        Attributes to be printed, as a list of "x=y" strings.
    """

    if extra_properties is None:
        if any(
            (
                with_visible,
                with_clickable,
                with_center_coords,
                with_bounding_box_coords,
                with_som,
                filter_visible_only,
                filter_with_bid_only,
                filter_som_only,
            )
        ):
            extra_properties = {}
        else:
            extra_properties = {}

    skip_element = False
    attributes_to_print = []

    if bid is None:
        # skip nodes without a bid (if requested)
        if filter_with_bid_only:
            skip_element = True
        if filter_som_only:
            skip_element = True
        if filter_visible_only:
            # Use DOM's is_visible property if available
            if node.is_visible is False:
                skip_element = True

    # parse extra browsergym properties, if node has a bid
    else:
        if bid in extra_properties:
            node_vis = extra_properties[bid]["visibility"]
            node_bbox = extra_properties[bid]["bbox"]
            node_is_clickable = extra_properties[bid]["clickable"]
            node_in_som = extra_properties[bid]["set_of_marks"]
            node_is_visible = node_vis >= 0.5
            # skip non-visible nodes (if requested)
            if filter_visible_only and not node_is_visible:
                skip_element = True
            if filter_som_only and not node_in_som:
                skip_element = True
            # print extra attributes if requested (with new names)
            if with_som and node_in_som:
                attributes_to_print.insert(0, "som")
            if with_visible and node_is_visible:
                attributes_to_print.insert(0, "visible")
            if with_clickable and node_is_clickable:
                attributes_to_print.insert(0, "clickable")
            if with_center_coords and node_bbox is not None:
                x, y, width, height = node_bbox
                center = (x + width / 2, y + height / 2)
                attributes_to_print.insert(0, f'center="{_get_coord_str(center, coord_decimals)}"')
            if with_bounding_box_coords and node_bbox is not None:
                x, y, width, height = node_bbox
                box = (x, y, x + width, y + height)
                attributes_to_print.insert(0, f'box="{_get_coord_str(box, coord_decimals)}"')
        else:
            # Use DOM properties when extra_properties not available
            if filter_visible_only and node.is_visible is False:
                skip_element = True
            if with_visible and node.is_visible:
                attributes_to_print.insert(0, "visible")
            if with_clickable and node.is_interactive:
                attributes_to_print.insert(0, "clickable")

    return skip_element, attributes_to_print


def _get_coord_str(coord, decimals):
    """Helper function for coordinate formatting (same as original)"""
    if isinstance(coord, str):
        coord = list(map(float, ast.literal_eval(coord)))

    coord_format = f".{decimals}f"
    coord_str = ",".join([f"{c:{coord_format}}" for c in coord])
    return f"({coord_str})"
