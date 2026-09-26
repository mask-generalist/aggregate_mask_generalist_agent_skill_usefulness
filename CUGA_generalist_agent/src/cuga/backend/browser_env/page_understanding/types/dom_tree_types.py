"""
Pydantic models for DOM tree extraction results from Chrome extension
"""

import json
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class DomTreeArgs(BaseModel):
    """
    Arguments for DOM tree extraction
    """

    model_config = ConfigDict(populate_by_name=True)

    do_highlight_elements: Optional[bool] = Field(
        default=True, description="Whether to highlight interactive elements"
    )
    focus_highlight_index: Optional[int] = Field(
        default=-1, description="Index of element to focus highlight on (-1 for all)"
    )
    viewport_expansion: Optional[int] = Field(
        default=0,
        description="Viewport expansion for visibility checks (0 = current viewport, -1 = all elements)",
    )
    debug_mode: Optional[bool] = Field(default=False, description="Enable debug mode")


class NodeData(BaseModel):
    """
    Data for an element node in the DOM tree
    """

    model_config = ConfigDict(populate_by_name=True)

    tag_name: str = Field(alias="tagName", description="HTML tag name (lowercase)")
    attributes: Dict[str, Optional[str]] = Field(description="Element attributes as key-value pairs")
    xpath: str = Field(description="XPath to the element")
    dom_tree_id: Optional[int] = Field(
        default=None, alias="domTreeId", description="Unique DOM tree id assigned by extension"
    )
    children: List[str] = Field(description="List of child node IDs")
    is_visible: Optional[bool] = Field(
        default=None, alias="isVisible", description="Whether the element is visible"
    )
    is_top_element: Optional[bool] = Field(
        default=None, alias="isTopElement", description="Whether the element is the topmost at its position"
    )
    is_interactive: Optional[bool] = Field(
        default=None, alias="isInteractive", description="Whether the element is interactive"
    )
    is_in_viewport: Optional[bool] = Field(
        default=None, alias="isInViewport", description="Whether the element is in the viewport"
    )
    highlight_index: Optional[int] = Field(
        default=None, alias="highlightIndex", description="Highlight index if element is highlighted"
    )
    shadow_root: Optional[bool] = Field(
        default=None, alias="shadowRoot", description="Whether the element has a shadow root"
    )

    def __str__(self) -> str:
        # Attributes as HTML-like pairs, truncating long values
        attr_parts = []
        for k, v in sorted((self.attributes or {}).items()):
            if v is None or v is True:
                attr_parts.append(k)
            elif v is False:
                attr_parts.append(f'{k}=false')
            else:
                val = str(v).replace('"', '\\"')
                if len(val) > 40:
                    val = val[:37] + "..."
                attr_parts.append(f'{k}="{val}"')
        attrs_str = " ".join(attr_parts) if attr_parts else "-"

        # Flags using field aliases (e.g., isVisible) and skipping None
        def flag(field_name: str):
            val = getattr(self, field_name)
            if val is None:
                return None
            alias = self.model_fields[field_name].alias or field_name
            return f"{alias}={'true' if val else 'false'}"

        flags = [flag(n) for n in ("is_visible", "is_top_element", "is_interactive", "is_in_viewport")]
        flags_str = " ".join(f for f in flags if f)

        hi = f"#{self.highlight_index}" if self.highlight_index is not None else ""
        sr = " shadowRoot" if self.shadow_root else ""
        dtid = self.dom_tree_id if self.dom_tree_id is not None else "-"

        return (
            f"<{self.tag_name}{hi}{sr} domTreeId={dtid} children={len(self.children)} "
            f"{flags_str} xpath='{self.xpath}' attrs=[{attrs_str}]>"
        )

    __repr__ = __str__

    def to_pretty_string(self) -> str:
        """Multiline JSON-style view with aliases; replaces 'children' with a count."""
        data = self.model_dump(by_alias=True, exclude_none=True)
        data["childrenCount"] = len(self.children)
        data.pop("children", None)
        return json.dumps(data, ensure_ascii=False, indent=2)


class TextNodeData(BaseModel):
    """
    Data for a text node in the DOM tree
    """

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["TEXT_NODE"] = Field(description="Node type discriminator")
    text: str = Field(description="Text content")
    is_visible: bool = Field(alias="isVisible", description="Whether the text node is visible")


class DomTreeResult(BaseModel):
    """
    Result of DOM tree extraction
    """

    model_config = ConfigDict(populate_by_name=True)

    root_id: str = Field(alias="rootId", description="ID of the root node")
    map: Dict[str, Union[NodeData, TextNodeData]] = Field(description="Map of node IDs to node data")

    def get_node(self, node_id: str) -> Optional[Union[NodeData, TextNodeData]]:
        """Get a node by its ID"""
        return self.map.get(node_id)

    def get_root_node(self) -> Optional[Union[NodeData, TextNodeData]]:
        """Get the root node"""
        return self.get_node(self.root_id)

    def get_interactive_nodes(self) -> List[NodeData]:
        """Get all interactive element nodes"""
        interactive_nodes = []
        for node in self.map.values():
            if isinstance(node, NodeData) and node.is_interactive:
                interactive_nodes.append(node)
        return interactive_nodes

    def get_highlighted_nodes(self) -> List[NodeData]:
        """Get all highlighted element nodes"""
        highlighted_nodes = []
        for node in self.map.values():
            if isinstance(node, NodeData) and node.highlight_index is not None:
                highlighted_nodes.append(node)
        return sorted(highlighted_nodes, key=lambda x: x.highlight_index or 0)

    def get_visible_text_nodes(self) -> List[TextNodeData]:
        """Get all visible text nodes"""
        text_nodes = []
        for node in self.map.values():
            if isinstance(node, TextNodeData) and node.is_visible:
                text_nodes.append(node)
        return text_nodes

    def get_children(self, node_id: str) -> List[Union[NodeData, TextNodeData]]:
        """Get all children of a node"""
        node = self.get_node(node_id)
        if isinstance(node, NodeData):
            return [
                self.get_node(child_id) for child_id in node.children if self.get_node(child_id) is not None
            ]
        return []

    def traverse_tree(self, node_id: Optional[str] = None) -> List[Union[NodeData, TextNodeData]]:
        """Traverse the tree in depth-first order"""
        if node_id is None:
            node_id = self.root_id

        result = []
        node = self.get_node(node_id)
        if node is None:
            return result

        result.append(node)

        if isinstance(node, NodeData):
            for child_id in node.children:
                result.extend(self.traverse_tree(child_id))

        return result

    def get_statistics(self) -> Dict[str, int]:
        """Get statistics about the DOM tree"""
        stats = {
            "total_nodes": len(self.map),
            "element_nodes": 0,
            "text_nodes": 0,
            "interactive_nodes": 0,
            "highlighted_nodes": 0,
            "visible_nodes": 0,
            "in_viewport_nodes": 0,
        }

        for node in self.map.values():
            if isinstance(node, NodeData):
                stats["element_nodes"] += 1
                if node.is_interactive:
                    stats["interactive_nodes"] += 1
                if node.highlight_index is not None:
                    stats["highlighted_nodes"] += 1
                if node.is_visible:
                    stats["visible_nodes"] += 1
                if node.is_in_viewport:
                    stats["in_viewport_nodes"] += 1
            elif isinstance(node, TextNodeData):
                stats["text_nodes"] += 1
                if node.is_visible:
                    stats["visible_nodes"] += 1

        return stats


# Type alias for convenience
DomTreeNode = Union[NodeData, TextNodeData]
