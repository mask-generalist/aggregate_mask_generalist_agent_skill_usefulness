"""
Test array handling in OpenAPI parsers.

This module tests both the main SimpleOpenAPIParser and the v0 OpenAPITransformer
to ensure arrays are handled correctly according to OpenAPI standards.
"""

import unittest

from cuga.backend.tools_env.registry.mcp_manager.openapi_parser import SimpleOpenAPIParser
from cuga.backend.tools_env.registry.mcp_manager.openapi_parser_v0 import OpenAPITransformer


class TestArrayHandling(unittest.TestCase):
    """Test array handling in OpenAPI parsers."""

    def setUp(self):
        """Set up test fixtures with various array schemas."""
        self.test_schema = {
            "openapi": "3.0.0",
            "info": {"title": "Array Test API", "version": "1.0.0"},
            "paths": {
                "/test-arrays": {
                    "post": {
                        "summary": "Test array parameters",
                        "parameters": [
                            {
                                "name": "job_titles",
                                "in": "query",
                                "required": True,
                                "description": "Array of job titles",
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "string", "title": "Job Title"},
                                },
                            },
                            {
                                "name": "user_ids",
                                "in": "query",
                                "required": False,
                                "description": "Array of user IDs",
                                "schema": {"type": "array", "items": {"type": "integer"}},
                            },
                            {
                                "name": "complex_objects",
                                "in": "query",
                                "required": False,
                                "description": "Array of complex objects",
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "age": {"type": "integer"},
                                        },
                                        "required": ["name"],
                                    },
                                },
                            },
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "tags": {"type": "array", "items": {"type": "string"}},
                                            "metadata": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "key": {"type": "string"},
                                                        "value": {"type": "string"},
                                                    },
                                                },
                                            },
                                        },
                                        "required": ["tags"],
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "results": {"type": "array", "items": {"type": "string"}}
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

    def test_main_parser_array_handling(self):
        """Test that the main SimpleOpenAPIParser handles arrays correctly."""
        parser = SimpleOpenAPIParser(self.test_schema)
        apis = parser.apis()

        # Should have one API
        self.assertEqual(len(apis), 1)
        api = apis[0]

        # Test array parameters
        array_params = [p for p in api.parameters if p.schema_field and p.schema_field.type == "array"]
        self.assertEqual(len(array_params), 3)

        # Test job_titles parameter
        job_titles_param = next(p for p in array_params if p.name == "job_titles")
        self.assertEqual(job_titles_param.schema_field.type, "array")
        self.assertIsNotNone(job_titles_param.schema_field.items)
        self.assertEqual(job_titles_param.schema_field.items.type, "string")
        self.assertTrue(job_titles_param.required)

        # Test user_ids parameter
        user_ids_param = next(p for p in array_params if p.name == "user_ids")
        self.assertEqual(user_ids_param.schema_field.type, "array")
        self.assertIsNotNone(user_ids_param.schema_field.items)
        self.assertEqual(user_ids_param.schema_field.items.type, "integer")
        self.assertFalse(user_ids_param.required)

        # Test complex_objects parameter
        complex_objects_param = next(p for p in array_params if p.name == "complex_objects")
        self.assertEqual(complex_objects_param.schema_field.type, "array")
        self.assertIsNotNone(complex_objects_param.schema_field.items)
        self.assertEqual(complex_objects_param.schema_field.items.type, "object")
        self.assertIn("name", complex_objects_param.schema_field.items.properties)
        self.assertIn("age", complex_objects_param.schema_field.items.properties)

        # Test request body arrays
        self.assertIsNotNone(api.request_body)
        json_content = api.request_body.content.get("application/json")
        self.assertIsNotNone(json_content)
        self.assertIsNotNone(json_content.schema_field)

        # Test tags array in request body
        tags_prop = json_content.schema_field.properties.get("tags")
        self.assertIsNotNone(tags_prop)
        self.assertEqual(tags_prop.type, "array")
        self.assertIsNotNone(tags_prop.items)
        self.assertEqual(tags_prop.items.type, "string")

        # Test metadata array in request body
        metadata_prop = json_content.schema_field.properties.get("metadata")
        self.assertIsNotNone(metadata_prop)
        self.assertEqual(metadata_prop.type, "array")
        self.assertIsNotNone(metadata_prop.items)
        self.assertEqual(metadata_prop.items.type, "object")
        self.assertIn("key", metadata_prop.items.properties)
        self.assertIn("value", metadata_prop.items.properties)

    def test_v0_parser_array_handling(self):
        """Test that the v0 OpenAPITransformer handles arrays correctly."""
        transformer = OpenAPITransformer(self.test_schema)
        result = transformer.transform()

        # Should have one API
        self.assertEqual(len(result), 1)
        api_name, api_data = next(iter(result.items()))

        # Test array parameters
        array_params = [p for p in api_data['parameters'] if p['type'] == 'array']
        self.assertGreaterEqual(len(array_params), 3)  # At least 3 array params

        # Test job_titles parameter
        job_titles_param = next(p for p in array_params if p['name'] == 'job_titles')
        self.assertEqual(job_titles_param['type'], 'array')
        self.assertIsNotNone(job_titles_param['schema'])
        self.assertIsInstance(job_titles_param['schema'], dict)
        self.assertEqual(job_titles_param['schema']['type'], 'array')
        self.assertEqual(job_titles_param['schema']['items'], 'string')
        self.assertTrue(job_titles_param['required'])

        # Test user_ids parameter
        user_ids_param = next(p for p in array_params if p['name'] == 'user_ids')
        self.assertEqual(user_ids_param['type'], 'array')
        self.assertIsNotNone(user_ids_param['schema'])
        self.assertIsInstance(user_ids_param['schema'], dict)
        self.assertEqual(user_ids_param['schema']['type'], 'array')
        self.assertEqual(user_ids_param['schema']['items'], 'integer')
        self.assertFalse(user_ids_param['required'])

        # Test complex_objects parameter
        complex_objects_param = next(p for p in array_params if p['name'] == 'complex_objects')
        self.assertEqual(complex_objects_param['type'], 'array')
        self.assertIsNotNone(complex_objects_param['schema'])
        self.assertIsInstance(complex_objects_param['schema'], dict)
        self.assertEqual(complex_objects_param['schema']['type'], 'array')
        items_schema = complex_objects_param['schema']['items']
        self.assertIsInstance(items_schema, dict)
        self.assertIn('name', items_schema)
        self.assertIn('age', items_schema)
        self.assertEqual(items_schema['name'], 'string')
        self.assertEqual(items_schema['age'], 'integer')

    def test_specific_array_issue_fix(self):
        """Test the specific array issue mentioned in the user query."""
        # This is the problematic schema format that was being generated before the fix
        problematic_schema = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/test": {
                    "post": {
                        "parameters": [
                            {
                                "name": "job_titles",
                                "in": "query",
                                "required": True,
                                "description": "Array of job titles",
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "string", "title": "Job Title"},
                                },
                            }
                        ]
                    }
                }
            },
        }

        transformer = OpenAPITransformer(problematic_schema)
        result = transformer.transform()

        # Should have one API
        self.assertEqual(len(result), 1)
        api_name, api_data = next(iter(result.items()))

        # Find the job_titles parameter
        job_titles_param = next(p for p in api_data['parameters'] if p['name'] == 'job_titles')

        # Verify the array schema is properly formatted
        self.assertEqual(job_titles_param['type'], 'array')
        self.assertIsNotNone(job_titles_param['schema'])
        self.assertIsInstance(job_titles_param['schema'], dict)

        # This should now be properly formatted as:
        # {"type": "array", "items": "string"}
        # instead of the old incorrect format:
        # [{"title": "string"}]
        schema = job_titles_param['schema']
        self.assertEqual(schema['type'], 'array')
        self.assertIn('items', schema)
        self.assertEqual(schema['items'], 'string')

        # Ensure it's not the old incorrect format
        self.assertNotIsInstance(schema, list)
        self.assertNotIn('title', schema)

    def test_array_with_enum_items(self):
        """Test arrays with enum items."""
        enum_array_schema = {
            "openapi": "3.0.0",
            "info": {"title": "Enum Array Test", "version": "1.0.0"},
            "paths": {
                "/test-enum-array": {
                    "post": {
                        "parameters": [
                            {
                                "name": "statuses",
                                "in": "query",
                                "required": True,
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "string", "enum": ["active", "inactive", "pending"]},
                                },
                            }
                        ]
                    }
                }
            },
        }

        # Test main parser
        parser = SimpleOpenAPIParser(enum_array_schema)
        apis = parser.apis()
        self.assertEqual(len(apis), 1)

        api = apis[0]
        statuses_param = next(p for p in api.parameters if p.name == "statuses")
        self.assertEqual(statuses_param.schema_field.type, "array")
        self.assertIsNotNone(statuses_param.schema_field.items)
        self.assertEqual(statuses_param.schema_field.items.type, "string")
        self.assertEqual(statuses_param.schema_field.items.enum, ["active", "inactive", "pending"])

        # Test v0 parser
        transformer = OpenAPITransformer(enum_array_schema)
        result = transformer.transform()
        self.assertEqual(len(result), 1)

        api_name, api_data = next(iter(result.items()))
        statuses_param = next(p for p in api_data['parameters'] if p['name'] == 'statuses')
        self.assertEqual(statuses_param['type'], 'array')
        self.assertIsNotNone(statuses_param['schema'])
        self.assertEqual(statuses_param['schema']['type'], 'array')
        # The v0 parser should handle enum items correctly
        self.assertIn('items', statuses_param['schema'])

    def test_nested_array_handling(self):
        """Test arrays of arrays (nested arrays)."""
        nested_array_schema = {
            "openapi": "3.0.0",
            "info": {"title": "Nested Array Test", "version": "1.0.0"},
            "paths": {
                "/test-nested-array": {
                    "post": {
                        "parameters": [
                            {
                                "name": "matrix",
                                "in": "query",
                                "required": True,
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "array", "items": {"type": "number"}},
                                },
                            }
                        ]
                    }
                }
            },
        }

        # Test main parser
        parser = SimpleOpenAPIParser(nested_array_schema)
        apis = parser.apis()
        self.assertEqual(len(apis), 1)

        api = apis[0]
        matrix_param = next(p for p in api.parameters if p.name == "matrix")
        self.assertEqual(matrix_param.schema_field.type, "array")
        self.assertIsNotNone(matrix_param.schema_field.items)
        self.assertEqual(matrix_param.schema_field.items.type, "array")
        self.assertIsNotNone(matrix_param.schema_field.items.items)
        self.assertEqual(matrix_param.schema_field.items.items.type, "number")

        # Test v0 parser
        transformer = OpenAPITransformer(nested_array_schema)
        result = transformer.transform()
        self.assertEqual(len(result), 1)

        api_name, api_data = next(iter(result.items()))
        matrix_param = next(p for p in api_data['parameters'] if p['name'] == 'matrix')
        self.assertEqual(matrix_param['type'], 'array')
        self.assertIsNotNone(matrix_param['schema'])
        self.assertEqual(matrix_param['schema']['type'], 'array')
        # The v0 parser should handle nested arrays correctly
        items = matrix_param['schema']['items']
        self.assertIsInstance(items, dict)
        self.assertEqual(items['type'], 'array')

    def test_array_constraints(self):
        """Test arrays with constraints like minItems, maxItems, uniqueItems."""
        constrained_array_schema = {
            "openapi": "3.0.0",
            "info": {"title": "Constrained Array Test", "version": "1.0.0"},
            "paths": {
                "/test-constrained-array": {
                    "post": {
                        "parameters": [
                            {
                                "name": "limited_items",
                                "in": "query",
                                "required": True,
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                    "maxItems": 10,
                                    "uniqueItems": True,
                                },
                            }
                        ]
                    }
                }
            },
        }

        # Test main parser
        parser = SimpleOpenAPIParser(constrained_array_schema)
        apis = parser.apis()
        self.assertEqual(len(apis), 1)

        api = apis[0]
        limited_items_param = next(p for p in api.parameters if p.name == "limited_items")
        self.assertEqual(limited_items_param.schema_field.type, "array")
        self.assertIsNotNone(limited_items_param.schema_field.items)
        self.assertEqual(limited_items_param.schema_field.items.type, "string")

        # Test v0 parser
        transformer = OpenAPITransformer(constrained_array_schema)
        result = transformer.transform()
        self.assertEqual(len(result), 1)

        api_name, api_data = next(iter(result.items()))
        limited_items_param = next(p for p in api_data['parameters'] if p['name'] == 'limited_items')
        self.assertEqual(limited_items_param['type'], 'array')
        self.assertIsNotNone(limited_items_param['schema'])
        self.assertEqual(limited_items_param['schema']['type'], 'array')

        # Check that constraints are included in the constraints list
        constraints = limited_items_param['constraints']
        constraint_text = ' '.join(constraints)
        self.assertIn('min items: 1', constraint_text)
        self.assertIn('max items: 10', constraint_text)
        self.assertIn('items must be unique', constraint_text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
