# Copyright 2024 ServiceNow
# Modifications Copyright 2025 CUGA
# Licensed under the Apache License, Version 2.0

import ast

IGNORED_AXTREE_ROLES = ["LineBreak"]

IGNORED_AXTREE_PROPERTIES = (
    "editable",
    "readonly",
    "level",
    "settable",
    "multiline",
    "invalid",
    "focusable",
)


def flatten_axtree_to_str(
    AX_tree,
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
    ignored_roles=IGNORED_AXTREE_ROLES,
    ignored_properties=IGNORED_AXTREE_PROPERTIES,
    remove_redundant_static_text: bool = True,
    hide_bid_if_invisible: bool = False,
    hide_all_children: bool = False,
    hide_all_bids: bool = False,
) -> str:
    """Formats the accessibility tree into a string text"""
    node_id_to_idx = {}
    for idx, node in enumerate(AX_tree["nodes"]):
        node_id_to_idx[node["nodeId"]] = idx

    def dfs(node_idx: int, depth: int, parent_node_filtered: bool, parent_node_name: str) -> str:
        tree_str = ""
        node = AX_tree["nodes"][node_idx]
        indent = "\t" * depth
        skip_node = False  # node will not be printed, with no effect on children nodes
        filter_node = False  # node will not be printed, possibly along with its children nodes
        node_role = node["role"]["value"]
        node_name = ""

        if node_role in ignored_roles:
            skip_node = True
            pass
        elif "name" not in node:
            skip_node = True
            pass
        else:
            node_name = node["name"]["value"]
            if "value" in node and "value" in node["value"]:
                node_value = node["value"]["value"]
            else:
                node_value = None

            # extract bid
            bid = node.get("browsergym_id", None)

            # extract node attributes
            attributes = []
            for property in node.get("properties", []):
                if "value" not in property:
                    continue
                if "value" not in property["value"]:
                    continue

                prop_name = property["name"]
                prop_value = property["value"]["value"]

                if prop_name in ignored_properties:
                    continue
                elif prop_name in ("required", "focused", "atomic"):
                    if prop_value:
                        attributes.append(prop_name)
                else:
                    attributes.append(f"{prop_name}={repr(prop_value)}")

            if skip_generic and node_role == "generic" and not attributes:
                skip_node = True

            if hide_all_children and parent_node_filtered:
                skip_node = True

            if node_role == "StaticText":
                if parent_node_filtered:
                    skip_node = True
                elif remove_redundant_static_text and node_name in parent_node_name:
                    skip_node = True
            else:
                filter_node, extra_attributes_to_print = _process_bid(
                    bid,
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
                if node_role == "generic" and not node_name:
                    node_str = f"{node_role}"
                else:
                    node_str = f"{node_role} {repr(node_name.strip())}"

                if not (
                    hide_all_bids
                    or bid is None
                    or (hide_bid_if_invisible and extra_properties.get(bid, {}).get("visibility", 0) < 0.5)
                ):
                    node_str = f"[{bid}] " + node_str

                if node_value is not None:
                    node_str += f' value={repr(node["value"]["value"])}'

                if attributes:
                    node_str += ", ".join([""] + attributes)

                tree_str += f"{indent}{node_str}"

        for child_node_id in node["childIds"]:
            if child_node_id not in node_id_to_idx or child_node_id == node["nodeId"]:
                continue
            # mark this to save some tokens
            child_depth = depth if skip_node else (depth + 1)
            child_str = dfs(
                node_id_to_idx[child_node_id],
                child_depth,
                parent_node_filtered=filter_node,
                parent_node_name=node_name,
            )
            if child_str:
                if tree_str:
                    tree_str += "\n"
                tree_str += child_str

        return tree_str

    tree_str = dfs(0, 0, False, "")
    return tree_str


def _process_bid(
    bid,
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
    Process extra attributes and attribute-based filters, for the element with the given bid.

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
            raise ValueError("extra_properties argument required")
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
            # element without bid have no visibility mark, they could be visible or non-visible
            pass  # keep elements without visible property
            # skip_element = True  # filter elements without visible property

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

    return skip_element, attributes_to_print


def _get_coord_str(coord, decimals):
    if isinstance(coord, str):
        coord = list(map(float, ast.literal_eval(coord)))

    coord_format = f".{decimals}f"
    coord_str = ",".join([f"{c:{coord_format}}" for c in coord])
    return f"({coord_str})"
