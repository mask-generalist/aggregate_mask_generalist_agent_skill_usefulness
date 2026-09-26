"""
Test cases for enum handling in OpenAPI processing.

This module tests the fix for the typing.Literal enum bug where
build_model() fails when processing enum fields from OpenAPI specs.
"""

import unittest
from typing import Literal
from pydantic import BaseModel

from cuga.backend.tools_env.registry.mcp_manager.adapter import (
    build_model,
    _python_type_for_schema,
    extract_field_definitions,
)
from cuga.backend.tools_env.registry.mcp_manager.openapi_parser import SimpleOpenAPIParser


class TestEnumHandling(unittest.TestCase):
    """Test cases for enum field handling in OpenAPI processing."""

    def test_python_type_for_schema_with_enum(self):
        """Test that _python_type_for_schema creates Literal types for enums."""
        schema = {"type": "string", "enum": ["charcoal", "red", "blue", "green", "orange", "yellow"]}

        result = _python_type_for_schema(schema)

        # Should return a Literal type
        self.assertTrue(hasattr(result, '__origin__'))
        self.assertEqual(result.__origin__, Literal)

        # Should not be a regular Python type
        self.assertFalse(isinstance(result, type))

    def test_build_model_with_literal_types(self):
        """Test that build_model can handle typing.Literal types."""
        field_defs = {
            "color": (Literal[("charcoal", "red", "blue", "green", "orange", "yellow")], None),
            "priority": (Literal[("low", "medium", "high", "urgent")], None),
            "title": (str, None),
        }

        # This should not raise an exception
        model = build_model("TestModel", field_defs)

        # Verify the model was created
        self.assertTrue(issubclass(model, BaseModel))
        self.assertEqual(model.__name__, "TestModel")

        # Verify annotations are set correctly
        annotations = model.__annotations__
        self.assertIn("color", annotations)
        self.assertIn("priority", annotations)
        self.assertIn("title", annotations)

        # Verify the Literal types are preserved
        self.assertTrue(hasattr(annotations["color"], '__origin__'))
        self.assertTrue(hasattr(annotations["priority"], '__origin__'))
        self.assertEqual(annotations["title"], str)

    def test_build_model_with_mixed_types(self):
        """Test build_model with a mix of regular types and Literal types."""
        field_defs = {
            "id": (int, 0),
            "name": (str, ""),
            "status": (Literal[("active", "inactive", "pending")], "pending"),
            "count": (int, None),
        }

        model = build_model("MixedModel", field_defs)

        # Verify the model was created successfully
        self.assertTrue(issubclass(model, BaseModel))

        # Verify all fields are present
        annotations = model.__annotations__
        expected_fields = {"id", "name", "status", "count"}
        self.assertEqual(set(annotations.keys()), expected_fields)

        # Verify types are correct
        self.assertEqual(annotations["id"], int)
        self.assertEqual(annotations["name"], str)
        self.assertTrue(hasattr(annotations["status"], '__origin__'))
        self.assertEqual(annotations["count"], int)

    def test_build_model_with_nested_models(self):
        """Test build_model with nested models containing enum fields."""
        nested_field_defs = {"nested_color": (Literal[("red", "blue")], None), "nested_value": (str, "")}

        field_defs = {"top_level": (str, ""), "nested": nested_field_defs}

        model = build_model("NestedModel", field_defs)

        # Verify the model was created
        self.assertTrue(issubclass(model, BaseModel))

        # Verify nested model was created
        annotations = model.__annotations__
        self.assertIn("top_level", annotations)
        self.assertIn("nested", annotations)

        # The nested field should be a dynamically created model
        nested_model = annotations["nested"]
        self.assertTrue(issubclass(nested_model, BaseModel))
        self.assertTrue(nested_model.__name__.startswith("NestedModel"))

    def test_openapi_enum_processing_integration(self):
        """Test the full integration with OpenAPI enum processing."""
        # Create a simple OpenAPI spec with enum fields
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "test_operation",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "color": {"type": "string", "enum": ["red", "blue", "green"]},
                                            "priority": {"type": "string", "enum": ["low", "high"]},
                                            "name": {"type": "string"},
                                        },
                                        "required": ["color", "name"],
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {"application/json": {"schema": {"type": "object"}}},
                            }
                        },
                    }
                }
            },
        }

        # Parse the OpenAPI spec
        parser = SimpleOpenAPIParser(openapi_spec)
        apis = list(parser.apis())

        # Should have one API
        self.assertEqual(len(apis), 1)
        api = apis[0]

        # Extract field definitions (this is where the bug would occur)
        field_defs = extract_field_definitions(api)

        # Should have extracted the fields
        self.assertIn("color", field_defs)
        self.assertIn("priority", field_defs)
        self.assertIn("name", field_defs)

        # The color and priority fields should have Literal types
        color_type, color_default = field_defs["color"]
        priority_type, priority_default = field_defs["priority"]
        name_type, name_default = field_defs["name"]

        # Verify types
        self.assertTrue(hasattr(color_type, '__origin__'))
        self.assertTrue(hasattr(priority_type, '__origin__'))
        self.assertEqual(name_type, str)

        # Now test that build_model works with these field definitions
        model = build_model("TestAPIModel", field_defs)

        # Should create successfully
        self.assertTrue(issubclass(model, BaseModel))

        # Verify annotations
        annotations = model.__annotations__
        self.assertIn("color", annotations)
        self.assertIn("priority", annotations)
        self.assertIn("name", annotations)


if __name__ == "__main__":
    unittest.main()
