from collections.abc import Callable
from pydantic import BaseModel


class ToolDefinition(BaseModel):
    name: str
    description: str
    run: Callable[[dict], str]

def run_calculator(arguments: dict) -> str:
    expression = arguments.get("expression")

    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("calculator requires a non-empty 'expression' argument")

    allowed_characters = set("0123456789+-*/(). ")
    if any(character not in allowed_characters for character in expression):
        raise ValueError("calculator expression contains unsupported characters")

    result = eval(expression, {"__builtins__": {}}, {})
    return str(result)

def run_mock_search(arguments: dict) -> str:
    query = arguments.get("query")

    if not isinstance(query, str) or not query.strip():
        raise ValueError("mock_search requires a non-empty 'query' argument")

    normalized_query = query.strip().lower()

    documents = {
        "refund policy": "Annual plans can be refunded within 30 days of purchase.",
        "password reset": "Users can reset passwords from the account security page.",
    }

    return documents.get(normalized_query, "No mock search result found.")

def build_tool_registry() -> dict[str, ToolDefinition]:
    calculator = ToolDefinition(
        name="calculator",
        description="Evaluate a simple arithmetic expression.",
        run=run_calculator,
    )
    mock_search = ToolDefinition(
        name="mock_search",
        description="Return a canned search result for a simple query.",
        run=run_mock_search,
    )

    return {
        calculator.name: calculator,
        mock_search.name: mock_search,
    }