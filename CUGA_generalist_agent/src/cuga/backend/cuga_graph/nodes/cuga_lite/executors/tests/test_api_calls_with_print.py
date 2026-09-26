"""Test API calls with print statements similar to code executor behavior."""

import asyncio
import pytest
from unittest.mock import Mock

from cuga.backend.cuga_graph.state.agent_state import AgentState, VariablesManager
from cuga.backend.cuga_graph.nodes.cuga_lite.executors import CodeExecutor


@pytest.fixture
def mock_state():
    """Create a mock AgentState with VariablesManager."""
    state = Mock(spec=AgentState)
    state.variables_manager = VariablesManager()
    return state


@pytest.mark.asyncio
async def test_api_calls_with_print_dict(mock_state):
    """Test calling API functions and printing results in dictionary format."""

    # Mock API functions
    async def hockey_teams_in_year(year: int):
        """Mock hockey teams API call."""
        await asyncio.sleep(0.01)  # Simulate async call
        return {"teams": ["Team A", "Team B", "Team C"], "year": year}

    async def hockey_distinct_team_names(opponent_name: str, year: int):
        """Mock hockey distinct team names API call."""
        await asyncio.sleep(0.01)  # Simulate async call
        return {"teams": ["Team X", "Team Y"], "opponent": opponent_name, "year": year}

    # Code that calls APIs and prints results
    code = """
recent_year_response = await hockey_teams_in_year(year=2023)
partial_2000s_teams = await hockey_distinct_team_names(opponent_name="Toronto Maple Leafs", year=2002)
print({
    "recent_year_response": recent_year_response,
    "partial_2000s_teams": partial_2000s_teams
})
"""

    # Set up _locals with the mock API functions
    _locals = {
        "hockey_teams_in_year": hockey_teams_in_year,
        "hockey_distinct_team_names": hockey_distinct_team_names,
    }

    result, new_vars = await CodeExecutor.eval_with_tools_async(
        code=code,
        _locals=_locals,
        state=mock_state,
        mode='local',
    )

    # Verify print output contains the dictionary
    assert "recent_year_response" in result
    assert "partial_2000s_teams" in result
    assert "2023" in result or "Team A" in result  # Check for some content from response

    # Verify variables were created
    assert 'recent_year_response' in new_vars
    assert 'partial_2000s_teams' in new_vars

    # Verify variable values
    assert new_vars['recent_year_response']['year'] == 2023
    assert 'teams' in new_vars['recent_year_response']
    assert new_vars['partial_2000s_teams']['year'] == 2002
    assert new_vars['partial_2000s_teams']['opponent'] == "Toronto Maple Leafs"


@pytest.mark.asyncio
async def test_api_calls_with_separate_prints(mock_state):
    """Test calling API functions and printing results separately."""

    # Mock API functions
    async def hockey_teams_in_year(year: int):
        """Mock hockey teams API call."""
        await asyncio.sleep(0.01)
        return {"teams": ["Team A", "Team B"], "year": year}

    async def hockey_distinct_team_names(opponent_name: str, year: int):
        """Mock hockey distinct team names API call."""
        await asyncio.sleep(0.01)
        return {"teams": ["Team X"], "opponent": opponent_name, "year": year}

    # Code that calls APIs and prints each result separately
    code = """
recent_year_response = await hockey_teams_in_year(year=2023)
print(recent_year_response)

partial_2000s_teams = await hockey_distinct_team_names(opponent_name="Toronto Maple Leafs", year=2002)
print(partial_2000s_teams)
"""

    _locals = {
        "hockey_teams_in_year": hockey_teams_in_year,
        "hockey_distinct_team_names": hockey_distinct_team_names,
    }

    result, new_vars = await CodeExecutor.eval_with_tools_async(
        code=code,
        _locals=_locals,
        state=mock_state,
        mode='local',
    )

    # Verify both print outputs are in result
    assert "recent_year_response" in result or "2023" in result or "Team A" in result
    assert "partial_2000s_teams" in result or "2002" in result or "Toronto Maple Leafs" in result

    # Verify variables were created
    assert 'recent_year_response' in new_vars
    assert 'partial_2000s_teams' in new_vars


@pytest.mark.asyncio
async def test_api_calls_with_print_and_variable_access(mock_state):
    """Test API calls where results are printed and then accessed as variables."""

    # Mock API function
    async def hockey_teams_in_year(year: int):
        """Mock hockey teams API call."""
        await asyncio.sleep(0.01)
        return {"teams": ["Team A", "Team B", "Team C"], "year": year, "count": 3}

    # Code that calls API, prints, and then uses the result
    code = """
recent_year_response = await hockey_teams_in_year(year=2023)
print(f"Found {recent_year_response['count']} teams in {recent_year_response['year']}")
print(recent_year_response)
"""

    _locals = {
        "hockey_teams_in_year": hockey_teams_in_year,
    }

    result, new_vars = await CodeExecutor.eval_with_tools_async(
        code=code,
        _locals=_locals,
        state=mock_state,
        mode='local',
    )

    # Verify print output
    assert "Found" in result
    assert "3" in result  # count
    assert "2023" in result  # year

    # Verify variable was created
    assert 'recent_year_response' in new_vars
    assert new_vars['recent_year_response']['count'] == 3
    assert new_vars['recent_year_response']['year'] == 2023


@pytest.mark.asyncio
async def test_api_calls_with_nested_dict_print(mock_state):
    """Test API calls with nested dictionary printing."""

    # Mock API functions
    async def hockey_teams_in_year(year: int):
        """Mock hockey teams API call."""
        await asyncio.sleep(0.01)
        return {"teams": ["Team A", "Team B"], "year": year}

    async def hockey_distinct_team_names(opponent_name: str, year: int):
        """Mock hockey distinct team names API call."""
        await asyncio.sleep(0.01)
        return {"teams": ["Team X"], "opponent": opponent_name, "year": year}

    # Code that creates nested structure and prints
    code = """
recent_year_response = await hockey_teams_in_year(year=2023)
partial_2000s_teams = await hockey_distinct_team_names(opponent_name="Toronto Maple Leafs", year=2002)

results = {
    "recent_year_response": recent_year_response,
    "partial_2000s_teams": partial_2000s_teams,
    "summary": {
        "recent_count": len(recent_year_response.get("teams", [])),
        "partial_count": len(partial_2000s_teams.get("teams", []))
    }
}
print(results)
"""

    _locals = {
        "hockey_teams_in_year": hockey_teams_in_year,
        "hockey_distinct_team_names": hockey_distinct_team_names,
    }

    result, new_vars = await CodeExecutor.eval_with_tools_async(
        code=code,
        _locals=_locals,
        state=mock_state,
        mode='local',
    )

    # Verify print output contains nested structure
    assert "recent_year_response" in result
    assert "partial_2000s_teams" in result
    assert "summary" in result

    # Verify all variables were created
    assert 'recent_year_response' in new_vars
    assert 'partial_2000s_teams' in new_vars
    assert 'results' in new_vars

    # Verify nested structure
    assert 'summary' in new_vars['results']
    assert new_vars['results']['summary']['recent_count'] == 2
    assert new_vars['results']['summary']['partial_count'] == 1


@pytest.mark.asyncio
async def test_api_calls_with_error_handling_and_print(mock_state):
    """Test API calls with error handling and print statements."""

    # Mock API function that raises an error
    async def hockey_teams_in_year(year: int):
        """Mock hockey teams API call that fails for certain years."""
        await asyncio.sleep(0.01)
        if year < 2000:
            raise ValueError(f"No data available for year {year}")
        return {"teams": ["Team A"], "year": year}

    # Code that handles errors and prints
    code = """
try:
    recent_year_response = await hockey_teams_in_year(year=1999)
    print(recent_year_response)
except Exception as e:
    error_msg = f"Error: {str(e)}"
    print(error_msg)
    recent_year_response = None

# Try a valid year
try:
    valid_response = await hockey_teams_in_year(year=2023)
    print(valid_response)
except Exception as e:
    print(f"Unexpected error: {e}")
    valid_response = None
"""

    _locals = {
        "hockey_teams_in_year": hockey_teams_in_year,
    }

    result, new_vars = await CodeExecutor.eval_with_tools_async(
        code=code,
        _locals=_locals,
        state=mock_state,
        mode='local',
    )

    # Verify error message is printed
    assert "Error" in result or "No data available" in result

    # Verify valid response is printed
    assert "2023" in result or "Team A" in result

    # Verify variables
    assert 'recent_year_response' in new_vars
    assert 'valid_response' in new_vars
    assert new_vars['recent_year_response'] is None
    assert new_vars['valid_response'] is not None
    assert new_vars['valid_response']['year'] == 2023
