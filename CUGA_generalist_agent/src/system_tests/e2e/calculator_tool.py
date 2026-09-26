from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from typing import Optional
import math


class EvaluateExpressionRequest(BaseModel):
    """Request model for evaluating mathematical expressions"""

    expression: str


class EvaluateExpressionResponse(BaseModel):
    """Response model for evaluated expressions"""

    expression: str
    result: float
    success: bool
    error_message: Optional[str] = None


class GetPiResponse(BaseModel):
    """Response model for getting pi value"""

    pi_value: float


class FactorialRequest(BaseModel):
    """Request model for calculating factorial"""

    n: int


class FactorialResponse(BaseModel):
    """Response model for factorial calculation"""

    n: int
    result: int
    success: bool
    error_message: Optional[str] = None


def evaluate_expression(expression: str) -> EvaluateExpressionResponse:
    """Evaluate a mathematical expression and return the result"""
    try:
        # Use eval with restricted globals for safety
        allowed_names = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
        allowed_names.update(
            {
                "abs": abs,
                "round": round,
                "min": min,
                "max": max,
                "sum": sum,
                "len": len,
                "pow": pow,
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "log": math.log,
                "exp": math.exp,
                "pi": math.pi,
                "e": math.e,
            }
        )

        # Evaluate the expression
        result = eval(expression, {"__builtins__": {}}, allowed_names)

        # Ensure result is a number
        if not isinstance(result, (int, float)):
            raise ValueError("Expression must evaluate to a number")

        return EvaluateExpressionResponse(expression=expression, result=float(result), success=True)
    except Exception as e:
        return EvaluateExpressionResponse(
            expression=expression, result=0.0, success=False, error_message=str(e)
        )


def get_pi() -> GetPiResponse:
    """Get the value of pi"""
    return GetPiResponse(pi_value=math.pi)


def calculate_factorial(n: int) -> FactorialResponse:
    """Calculate the factorial of a non-negative integer"""
    try:
        if not isinstance(n, int) or n < 0:
            raise ValueError("n must be a non-negative integer")

        result = math.factorial(n)
        return FactorialResponse(n=n, result=result, success=True)
    except Exception as e:
        return FactorialResponse(n=n, result=0, success=False, error_message=str(e))


# Create structured tools from the functions
evaluate_tool = StructuredTool.from_function(evaluate_expression)
pi_tool = StructuredTool.from_function(get_pi)
factorial_tool = StructuredTool.from_function(calculate_factorial)

# Export all tools
tools = [evaluate_tool, pi_tool, factorial_tool]
