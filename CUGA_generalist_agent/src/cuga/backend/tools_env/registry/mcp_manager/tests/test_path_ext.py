"""Unit test to validate path extraction logic for tool naming."""

from cuga.backend.tools_env.registry.mcp_manager.adapter import sanitize_tool_name


def test_path_extraction_logic():
    """Test the path extraction logic used in adapter.py for tool naming."""

    # Test cases: (path, operation_id, expected_first_word)
    # Note: The actual implementation uses the first segment directly (not split on hyphens/underscores)
    test_cases = [
        # Normal paths with first segment
        ("/api/v1/users", "getUsers", "api"),
        ("/users/{id}", "getUserById", "users"),
        ("/health", "checkHealth", "health"),
        ("/api/v2/claims", "getClaims", "api"),
        ("/get_plan_information", "getPlanInformation", "get_plan_information"),  # Full first segment
        ("/create_coverage_period", "createCoveragePeriod", "create_coverage_period"),  # Full first segment
        # Paths without leading slash
        ("api/v1/users", "getUsers", "api"),
        ("users", "getUsers", "users"),
        ("get_plan_information", "getPlanInformation", "get_plan_information"),
        # Edge cases
        ("/", "getRoot", "getRoot"),  # Should fallback to operation_id
        ("", "getDefault", "getDefault"),  # Should fallback to operation_id
        (None, "getNone", "getNone"),  # Should fallback to operation_id
        ("//api", "getApi", "api"),  # Multiple slashes
        ("   ", "getWhitespace", "getWhitespace"),  # Whitespace only
        # Paths with special characters - first segment is used as-is
        ("/api-v2/users", "getUsers", "api-v2"),
        ("/api.v1/users", "getUsers", "api.v1"),
        # Empty operation_id fallback
        ("", "", "unnamed"),  # Should fallback to "unnamed"
        (None, None, "unnamed"),  # Should fallback to "unnamed"
    ]

    prefix = "test_prefix"

    for path, operation_id, expected_first_word in test_cases:
        # Simulate the actual logic from adapter.py (uses first segment directly, not split)
        path_str = (path or "").strip()
        if path_str and path_str.strip('/'):
            first_segment = path_str.strip('/').split('/')[0]
            # Use the first segment directly (not split on hyphens/underscores)
            path_first_word = first_segment if first_segment else operation_id or "unnamed"
        else:
            path_first_word = operation_id or "unnamed"
        path_prefix = sanitize_tool_name(path_first_word)
        tool_name = sanitize_tool_name(f"{prefix}_{path_prefix}")

        # Validate the result
        expected_tool_name = sanitize_tool_name(f"{prefix}_{sanitize_tool_name(expected_first_word)}")

        path_display = repr(path) if path is not None else "None"
        print(
            f"Path: {path_display} (op_id: '{operation_id}') -> First word: '{path_first_word}' -> Tool name: '{tool_name}'"
        )
        print(f"  Expected: '{expected_tool_name}'")

        assert tool_name == expected_tool_name, (
            f"Failed for path {path_display}: expected '{expected_tool_name}', got '{tool_name}'"
        )
        print("  ✓ PASSED\n")


if __name__ == "__main__":
    test_path_extraction_logic()
    print("All tests passed!")
