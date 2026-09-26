# DOM Tree Types

Pydantic models for DOM tree extraction results from the Chrome extension.

## Overview

The DOM tree extraction provides a structured representation of the web page's DOM with interactive element analysis and highlighting capabilities.

## Models

### `DomTreeArgs`
Input arguments for DOM tree extraction:
- `do_highlight_elements`: Whether to highlight interactive elements (default: True)
- `focus_highlight_index`: Index of element to focus highlight on, -1 for all (default: -1)
- `viewport_expansion`: Viewport expansion for visibility checks, 0 = current viewport, -1 = all elements (default: 0)
- `debug_mode`: Enable debug mode (default: False)

### `NodeData`
Represents an element node in the DOM tree:
- `tag_name` (alias: `tagName`): HTML tag name (lowercase)
- `attributes`: Element attributes as key-value pairs
- `xpath`: XPath to the element
- `children`: List of child node IDs
- `is_visible` (alias: `isVisible`): Whether the element is visible (optional)
- `is_top_element` (alias: `isTopElement`): Whether the element is the topmost at its position (optional)
- `is_interactive` (alias: `isInteractive`): Whether the element is interactive (optional)
- `is_in_viewport` (alias: `isInViewport`): Whether the element is in the viewport (optional)
- `highlight_index` (alias: `highlightIndex`): Highlight index if element is highlighted (optional)
- `shadow_root` (alias: `shadowRoot`): Whether the element has a shadow root (optional)

### `TextNodeData`
Represents a text node in the DOM tree:
- `type`: Always "TEXT_NODE" (literal type)
- `text`: Text content
- `is_visible` (alias: `isVisible`): Whether the text node is visible

### `DomTreeResult`
Main result structure containing the complete DOM tree:
- `root_id` (alias: `rootId`): ID of the root node
- `map`: Dictionary mapping node IDs to node data

## Field Name Compatibility

The models support both Python snake_case and JavaScript camelCase field names through Pydantic aliases:

```python
# Both of these work identically:
node_data = NodeData(tagName="div", isVisible=True, ...)  # JavaScript style
node_data = NodeData(tag_name="div", is_visible=True, ...)  # Python style

# Access is always through snake_case attributes:
print(node_data.tag_name)  # "div"
print(node_data.is_visible)  # True
```

This ensures seamless integration with the Chrome extension's JavaScript data while maintaining Python conventions in your code.

## Utility Methods

The `DomTreeResult` class provides several utility methods:

- `get_node(node_id)`: Get a node by its ID
- `get_root_node()`: Get the root node
- `get_interactive_nodes()`: Get all interactive element nodes
- `get_highlighted_nodes()`: Get all highlighted element nodes (sorted by highlight index)
- `get_visible_text_nodes()`: Get all visible text nodes
- `get_children(node_id)`: Get all children of a node
- `traverse_tree(node_id=None)`: Traverse the tree in depth-first order
- `get_statistics()`: Get statistics about the DOM tree

## Usage Example

```python
from page_understanding.pu_extractor_chrome_extension import PageUnderstandingExtractorChromeExtension

async with PageUnderstandingExtractorChromeExtension() as extractor:
    result = await extractor.extract()
    
    if result.dom_tree:
        # Get statistics
        stats = result.dom_tree.get_statistics()
        print(f"Total nodes: {stats['total_nodes']}")
        print(f"Interactive nodes: {stats['interactive_nodes']}")
        
        # Get interactive elements
        interactive_nodes = result.dom_tree.get_interactive_nodes()
        for node in interactive_nodes:
            print(f"Interactive: <{node.tag_name}> at {node.xpath}")
            if node.highlight_index is not None:
                print(f"  Highlighted as #{node.highlight_index}")
        
        # Get highlighted elements (for debugging)
        highlighted_nodes = result.dom_tree.get_highlighted_nodes()
        for node in highlighted_nodes:
            print(f"#{node.highlight_index}: <{node.tag_name}> - {node.xpath}")
```

## Type Safety

The models provide full type safety with Pydantic validation:

```python
from page_understanding.types import DomTreeResult, NodeData, TextNodeData

# Type-safe access
def analyze_node(node: NodeData | TextNodeData):
    if isinstance(node, NodeData):
        print(f"Element: <{node.tag_name}>")
        if node.is_interactive:
            print("  This is an interactive element")
    elif isinstance(node, TextNodeData):
        print(f"Text: {node.text[:50]}...")
```

## Integration

The DOM tree types are automatically used in the `PUExtractedChromeExtension` result:

```python
result = await extractor.extract()
# result.dom_tree is now properly typed as Optional[DomTreeResult]
```