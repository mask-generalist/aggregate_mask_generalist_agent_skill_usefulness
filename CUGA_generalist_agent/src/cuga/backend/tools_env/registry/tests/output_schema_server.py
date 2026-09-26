"""
FastMCP Server with Various Output Types for Testing Response Schemas

This server demonstrates different output types:
- Simple types (int, str)
- Lists
- Dicts
- Pydantic models
- Error cases
"""

from typing import List
from pydantic import BaseModel
from fastmcp import FastMCP

mcp = FastMCP("Output Schema Test Server")


class UserModel(BaseModel):
    """User model with Pydantic validation"""

    id: int
    name: str
    email: str
    age: int


class ProductModel(BaseModel):
    """Product model"""

    id: int
    name: str
    price: float
    in_stock: bool


@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


@mcp.tool
def greet(name: str) -> str:
    """Greet someone"""
    return f"Hello, {name}!"


@mcp.tool
def get_items(count: int) -> List[str]:
    """Get a list of items"""
    return [f"item_{i}" for i in range(count)]


@mcp.tool
def calculate_sum(numbers: List[int]) -> dict:
    """Calculate sum of numbers"""
    return {"numbers": numbers, "sum": sum(numbers)}


@mcp.tool
def create_user(name: str, email: str, age: int) -> UserModel:
    """Create a user with Pydantic model"""
    return UserModel(id=1, name=name, email=email, age=age)


@mcp.tool
def get_products(count: int) -> List[ProductModel]:
    """Get a list of products"""
    return [
        ProductModel(id=i, name=f"Product {i}", price=10.0 * i, in_stock=i % 2 == 0) for i in range(count)
    ]


@mcp.tool
def raise_error(message: str) -> dict:
    """Raise an error on purpose for testing error handling"""
    raise ValueError(f"Intentional error: {message}")


@mcp.tool
def nested_dict(value: str) -> dict:
    """Return nested dictionary structure"""
    return {"data": {"nested": {"value": value}}}


@mcp.tool(
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "count": {"type": "integer"},
            "items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "count", "items"],
    }
)
def explicit_schema_tool(count: int) -> dict:
    """Tool with explicit output schema - returns status with item list"""
    return {"status": "success", "count": count, "items": [f"explicit_item_{i}" for i in range(count)]}


@mcp.tool(
    output_schema={
        "type": "object",
        "properties": {
            "user_info": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "email": {"type": "string"},
                    "is_active": {"type": "boolean"},
                },
                "required": ["username", "email"],
            },
            "metadata": {
                "type": "object",
                "properties": {"created_at": {"type": "string"}, "updated_at": {"type": "string"}},
            },
        },
        "required": ["user_info"],
    }
)
def complex_nested_schema(username: str, email: str) -> dict:
    """Tool with complex nested output schema"""
    return {
        "user_info": {"username": username, "email": email, "is_active": True},
        "metadata": {"created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"},
    }


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=8002)
