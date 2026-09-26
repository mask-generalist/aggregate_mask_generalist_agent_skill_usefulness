import asyncio
from unittest.mock import AsyncMock

import pytest

from agent_inspect.metrics.constants import (
    STATUS_200,
    NUM_JUDGE_TRIALS,
    INCLUDE_JUDGE_EXPLANATION,
    INCLUDE_PROMPT_SENT_TO_LLMJ,
    OPTIMIZE_JUDGE_TRIALS,
    CASE_SENSITIVE,
    EXACT_FUZZY_NO_MATCH_DICT,
    EXACT_FUZZY_NO_MATCH_GRADE_PATTERN,
)
from agent_inspect.exception import EvaluationError, InvalidInputValueError
from agent_inspect.metrics.validator import CapabilityCompletionValidator
from agent_inspect.models.metrics import (
    ToolInputParameter,
    TurnTrace,
    AgentResponse,
    Step,
)
from agent_inspect.models.metrics.capability_data_sample import (
    ExpectedCapability,
    CapabilityOutput,
)
from agent_inspect.models.metrics.skill_data_sample import SkillCall
from agent_inspect.models import LLMResponse


@pytest.fixture
def mock_turn_trace_tool_call():
    return TurnTrace(
        id="1",
        agent_input="Agent Input",
        steps=[
            Step(
                id="step1",
                parent_ids=[],
                tool="create_file",
                tool_input_args=[ToolInputParameter(name="path", value="/tmp/x")],
                tool_output="File created",
            )
        ],
        agent_response=AgentResponse(response="Done."),
    )


@pytest.fixture
def mock_turn_trace_thought_only():
    return TurnTrace(
        id="2",
        agent_input="Do something",
        steps=[
            Step(
                id="step1",
                parent_ids=[],
                agent_thought="Thinking about which tool to use",
            )
        ],
        agent_response=AgentResponse(response="I am thinking."),
    )


@pytest.fixture
def mock_expected_capability():
    return ExpectedCapability(
        capability_name="create_file",
        description="Create a file at the given path.",
    )


@pytest.fixture
def mock_expected_capability_full():
    return ExpectedCapability(
        capability_name="create_file",
        description="Create a file at the given path.",
        expected_output=CapabilityOutput(
            check="Does the file exist?",
        ),
    )


def _judge_responses(grade: str, count: int):
    return [
        LLMResponse(
            status=STATUS_200,
            completion=f"This is a dummy judge explanation.\n\nGRADE: {grade}",
            error_message="",
        )
        for _ in range(count)
    ]


# ---------------------------------------------------------------------------
# Formatter helpers
# ---------------------------------------------------------------------------
def test_format_expected_output_none(mock_expected_capability):
    result = CapabilityCompletionValidator.format_expected_output(mock_expected_capability)
    assert result == "No expected output specified."


def test_format_expected_output_with_output(mock_expected_capability_full):
    result = CapabilityCompletionValidator.format_expected_output(mock_expected_capability_full)
    assert result == "Expected value: Does the file exist?"


# ---------------------------------------------------------------------------
# Tool-call trajectory rendering
# ---------------------------------------------------------------------------
def test_format_tool_call_steps_str_handles_no_tool_calls(mock_turn_trace_thought_only):
    result = CapabilityCompletionValidator.format_tool_call_steps_str(
        [mock_turn_trace_thought_only]
    )
    assert result == "None"


def test_format_tool_call_steps_str_renders_only_tool_calls(
    mock_turn_trace_tool_call, mock_turn_trace_thought_only
):
    result = CapabilityCompletionValidator.format_tool_call_steps_str(
        [mock_turn_trace_tool_call, mock_turn_trace_thought_only]
    )
    assert result == (
        "{'id': 'step1', 'parent_ids': [], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'create_file', 'tool_arguments': {'path': '/tmp/x'}, "
        "'tool_output': 'File created'}}"
    )


def test_generate_prompt_includes_capability_and_tool_calls(
    mock_expected_capability, mock_turn_trace_tool_call
):
    prompt = CapabilityCompletionValidator.generate_prompt_from_capability_and_turn_traces(
        mock_expected_capability, [mock_turn_trace_tool_call]
    )
    assert "create_file" in prompt
    assert "Create a file at the given path." in prompt
    assert "No expected output specified." in prompt
    assert "'tool_name': 'create_file'" in prompt


def _data_region(prompt: str) -> str:
    """Slice out the dynamic portion of the prompt the method assembles.

    Returns everything from the ``[Ground Truth Capability]`` header up to (but not
    including) the ``[END DATA]`` marker, so exact-match assertions focus on the
    capability/tool-call content the method fills in rather than the static
    boilerplate instructions in the template (which would make tests brittle to
    unrelated wording tweaks).
    """
    start = prompt.index("[Ground Truth Capability]:")
    end = prompt.index("[END DATA]")
    return prompt[start:end]


def test_generate_prompt_data_region_minimal_capability(
    mock_expected_capability, mock_turn_trace_tool_call
):
    prompt = CapabilityCompletionValidator.generate_prompt_from_capability_and_turn_traces(
        mock_expected_capability, [mock_turn_trace_tool_call]
    )
    assert _data_region(prompt) == (
        "[Ground Truth Capability]:\n"
        "Capability name: create_file\n"
        "Description: Create a file at the given path.\n"
        "Expected output: No expected output specified.\n"
        "\n"
        "************\n"
        "[Agent Tool Call Steps]:\n"
        "{'id': 'step1', 'parent_ids': [], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'create_file', 'tool_arguments': {'path': '/tmp/x'}, "
        "'tool_output': 'File created'}}\n"
        "\n"
        "************\n"
    )


def test_generate_prompt_data_region_with_expected_output(mock_turn_trace_tool_call):
    capability = ExpectedCapability(
        capability_name="create_file",
        description="Create a file at the given path.",
        expected_output=CapabilityOutput(check="Does the file exist?"),
    )
    prompt = CapabilityCompletionValidator.generate_prompt_from_capability_and_turn_traces(
        capability, [mock_turn_trace_tool_call]
    )
    assert _data_region(prompt) == (
        "[Ground Truth Capability]:\n"
        "Capability name: create_file\n"
        "Description: Create a file at the given path.\n"
        "Expected output: Expected value: Does the file exist?\n"
        "\n"
        "************\n"
        "[Agent Tool Call Steps]:\n"
        "{'id': 'step1', 'parent_ids': [], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'create_file', 'tool_arguments': {'path': '/tmp/x'}, "
        "'tool_output': 'File created'}}\n"
        "\n"
        "************\n"
    )


def test_generate_prompt_data_region_empty_capability_name(mock_turn_trace_tool_call):
    # An empty capability_name is rendered as "Not specified" in the prompt.
    capability = ExpectedCapability(capability_name="", description="Create a file.")
    prompt = CapabilityCompletionValidator.generate_prompt_from_capability_and_turn_traces(
        capability, [mock_turn_trace_tool_call]
    )
    assert _data_region(prompt) == (
        "[Ground Truth Capability]:\n"
        "Capability name: Not specified\n"
        "Description: Create a file.\n"
        "Expected output: No expected output specified.\n"
        "\n"
        "************\n"
        "[Agent Tool Call Steps]:\n"
        "{'id': 'step1', 'parent_ids': [], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'create_file', 'tool_arguments': {'path': '/tmp/x'}, "
        "'tool_output': 'File created'}}\n"
        "\n"
        "************\n"
    )


def test_generate_prompt_data_region_no_tool_calls(mock_turn_trace_thought_only):
    # A trace with only a thought step renders the tool-call section as "None".
    capability = ExpectedCapability(capability_name="create_file", description="Create a file.")
    prompt = CapabilityCompletionValidator.generate_prompt_from_capability_and_turn_traces(
        capability, [mock_turn_trace_thought_only]
    )
    assert _data_region(prompt) == (
        "[Ground Truth Capability]:\n"
        "Capability name: create_file\n"
        "Description: Create a file.\n"
        "Expected output: No expected output specified.\n"
        "\n"
        "************\n"
        "[Agent Tool Call Steps]:\n"
        "None\n"
        "\n"
        "************\n"
    )


def test_generate_prompt_data_region_multiple_tool_calls_across_turns(
    mock_turn_trace_tool_call,
):
    # Tool-call steps from every turn are rendered in order, one per line.
    second_turn = TurnTrace(
        id="3",
        agent_input="z",
        steps=[
            Step(
                id="s1",
                parent_ids=[],
                tool="read_file",
                tool_input_args=[ToolInputParameter(name="p", value="/a")],
                tool_output="data",
            ),
            Step(
                id="s2",
                parent_ids=["s1"],
                tool="create_file",
                tool_input_args=[ToolInputParameter(name="path", value="/b")],
                tool_output="ok",
            ),
        ],
        agent_response=AgentResponse(response="done"),
    )
    capability = ExpectedCapability(capability_name="create_file", description="Create a file.")
    prompt = CapabilityCompletionValidator.generate_prompt_from_capability_and_turn_traces(
        capability, [mock_turn_trace_tool_call, second_turn]
    )
    assert _data_region(prompt) == (
        "[Ground Truth Capability]:\n"
        "Capability name: create_file\n"
        "Description: Create a file.\n"
        "Expected output: No expected output specified.\n"
        "\n"
        "************\n"
        "[Agent Tool Call Steps]:\n"
        "{'id': 'step1', 'parent_ids': [], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'create_file', 'tool_arguments': {'path': '/tmp/x'}, "
        "'tool_output': 'File created'}}\n"
        "{'id': 's1', 'parent_ids': [], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'read_file', 'tool_arguments': {'p': '/a'}, "
        "'tool_output': 'data'}}\n"
        "{'id': 's2', 'parent_ids': ['s1'], 'type': 'Tool Call', 'content': "
        "{'tool_name': 'create_file', 'tool_arguments': {'path': '/b'}, "
        "'tool_output': 'ok'}}\n"
        "\n"
        "************\n"
    )


# ---------------------------------------------------------------------------
# validate() — E / F / N grade handling
# ---------------------------------------------------------------------------
def test_validate_exact_match_is_completed(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("E", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(
        validator.validate([mock_turn_trace_tool_call], mock_expected_capability)
    )
    assert validation_result.is_completed
    assert validation_result.expected_capability == mock_expected_capability
    assert len(validation_result.explanations) == 1
    assert (
        validation_result.explanations[0]
        == 'Check: capability "create_file" has been invoked successfully.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_fuzzy_match_is_completed(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("F", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(
        validator.validate([mock_turn_trace_tool_call], mock_expected_capability)
    )
    assert validation_result.is_completed
    assert validation_result.expected_capability == mock_expected_capability
    assert (
        validation_result.explanations[0]
        == 'Check: capability "create_file" has been invoked successfully.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_no_match_is_incomplete(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("N", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(
        validator.validate([mock_turn_trace_tool_call], mock_expected_capability)
    )
    assert not validation_result.is_completed
    assert validation_result.expected_capability == mock_expected_capability
    assert (
        validation_result.explanations[0] == 'Check: capability "create_file" has not been invoked.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_exact_match_optimised(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 3:
            return _judge_responses("E", 3)
        raise AssertionError(f"Expected 3 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(
        llm_client=mock_llm_client, config={OPTIMIZE_JUDGE_TRIALS: True}
    )
    validation_result = asyncio.run(
        validator.validate([mock_turn_trace_tool_call], mock_expected_capability)
    )
    assert validation_result.is_completed
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_with_judge_explanation(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 3:
            return _judge_responses("E", 3)
        raise AssertionError(f"Expected 3 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(
        llm_client=mock_llm_client,
        config={INCLUDE_JUDGE_EXPLANATION: True, OPTIMIZE_JUDGE_TRIALS: True},
    )
    validation_result = asyncio.run(
        validator.validate([mock_turn_trace_tool_call], mock_expected_capability)
    )
    assert validation_result.is_completed
    assert len(validation_result.explanations) == 4
    assert (
        validation_result.explanations[0]
        == 'Check: capability "create_file" has been invoked successfully.'
    )
    assert validation_result.explanations[-1] == "This is a dummy judge explanation.\n\nGRADE: E"
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_with_prompt_sent_to_llmj(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 3:
            return _judge_responses("E", 3)
        raise AssertionError(f"Expected 3 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(
        llm_client=mock_llm_client,
        config={INCLUDE_PROMPT_SENT_TO_LLMJ: True, OPTIMIZE_JUDGE_TRIALS: True},
    )
    validation_result = asyncio.run(
        validator.validate([mock_turn_trace_tool_call], mock_expected_capability)
    )
    assert validation_result.is_completed
    assert validation_result.prompt_sent_to_llmj is not None
    assert "create_file" in validation_result.prompt_sent_to_llmj
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_empty_capability_name_is_allowed(mock_turn_trace_tool_call):
    # An empty capability_name no longer raises: the judge is invoked and, per the
    # prompt, may only return FUZZY_MATCH or NO_MATCH (EXACT_MATCH is impossible
    # without a capability name).
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("F", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(capability_name="", description="d")
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_tool_call], capability))
    assert validation_result.is_completed
    # With no capability_name, the completion message falls back to the description.
    assert (
        validation_result.explanations[0]
        == 'Check: capability with the description "d" has been invoked successfully.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_no_capability_name_not_completed_uses_description(mock_turn_trace_tool_call):
    # When the judge returns NO_MATCH and there is no capability_name, the
    # not-completed message also falls back to the description.
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("N", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(capability_name="", description="d")
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_tool_call], capability))
    assert not validation_result.is_completed
    assert (
        validation_result.explanations[0]
        == 'Check: capability with the description "d" has not been invoked.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_missing_description_raises(mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()
    invalid_capability = ExpectedCapability(capability_name="create_file", description="")

    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    with pytest.raises(
        InvalidInputValueError,
        match="The ExpectedCapability is missing a description for judge to evaluate.",
    ):
        asyncio.run(validator.validate([mock_turn_trace_tool_call], invalid_capability))


def test_validate_whitespace_capability_name_is_allowed(mock_turn_trace_tool_call):
    # A whitespace-only capability_name is treated the same as empty: no longer
    # raises, the judge is invoked.
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("F", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(capability_name="   ", description="d")
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_tool_call], capability))
    assert validation_result.is_completed
    # A whitespace-only capability_name also falls back to the description.
    assert (
        validation_result.explanations[0]
        == 'Check: capability with the description "d" has been invoked successfully.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_whitespace_description_raises(mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()
    invalid_capability = ExpectedCapability(capability_name="create_file", description="   ")

    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    with pytest.raises(
        InvalidInputValueError,
        match="The ExpectedCapability is missing a description for judge to evaluate.",
    ):
        asyncio.run(validator.validate([mock_turn_trace_tool_call], invalid_capability))


def test_validate_output_missing_check_raises(mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()
    invalid_capability = ExpectedCapability(
        capability_name="create_file",
        description="d",
        expected_output=CapabilityOutput(check=""),
    )

    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    with pytest.raises(
        InvalidInputValueError,
        match="The CapabilityOutput is missing a check for judge to evaluate.",
    ):
        asyncio.run(validator.validate([mock_turn_trace_tool_call], invalid_capability))


# ---------------------------------------------------------------------------
# Judge voting with the E/F/N pattern
# ---------------------------------------------------------------------------
def test_tally_judge_voting_efn_pattern():
    judge_responses = _judge_responses("E", 2) + _judge_responses("N", 1)
    grade_counts = {grade: 0 for grade in list(EXACT_FUZZY_NO_MATCH_DICT.keys())}

    grade_counts, invalid_cnt = CapabilityCompletionValidator._tally_judge_voting(
        judge_responses=judge_responses,
        regex_pattern=EXACT_FUZZY_NO_MATCH_GRADE_PATTERN,
        grade_counts_with_key=grade_counts,
    )
    assert grade_counts["E"] == 2
    assert grade_counts["F"] == 0
    assert grade_counts["N"] == 1
    assert invalid_cnt == 0


def test_tally_judge_voting_invalid_grades():
    judge_responses = [
        LLMResponse(
            status=STATUS_200, completion="Some explanation.\n\nGRADE: C", error_message=""
        ),
        LLMResponse(
            status=STATUS_200, completion="Some explanation.\n\nGRADE: I", error_message=""
        ),
    ]
    grade_counts = {grade: 0 for grade in list(EXACT_FUZZY_NO_MATCH_DICT.keys())}

    grade_counts, invalid_cnt = CapabilityCompletionValidator._tally_judge_voting(
        judge_responses=judge_responses,
        regex_pattern=EXACT_FUZZY_NO_MATCH_GRADE_PATTERN,
        grade_counts_with_key=grade_counts,
    )
    assert grade_counts["E"] == 0
    assert grade_counts["F"] == 0
    assert grade_counts["N"] == 0
    assert invalid_cnt == 2


def test_validate_invalid_trials_raises(mock_expected_capability, mock_turn_trace_tool_call):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        return [LLMResponse(status=STATUS_200, completion="", error_message="") for _ in prompts]

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    validator = CapabilityCompletionValidator(
        llm_client=mock_llm_client, config={NUM_JUDGE_TRIALS: 1, OPTIMIZE_JUDGE_TRIALS: True}
    )
    with pytest.raises(
        EvaluationError,
        match="Internal Code: 050007, Error Message: Could not reach majority decision due to insufficient valid judge responses.",
    ):
        asyncio.run(validator.validate([mock_turn_trace_tool_call], mock_expected_capability))


# ---------------------------------------------------------------------------
# expected_skills filtering
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_turn_trace_with_skill():
    return TurnTrace(
        id="1",
        agent_input="Agent Input",
        steps=[
            Step(
                id="skill_step",
                parent_ids=[],
                skill_calls=[SkillCall(skill_id="acme_vendor_onboarding")],
            ),
            Step(
                id="tool_step",
                parent_ids=["skill_step"],
                tool="create_file",
                tool_input_args=[ToolInputParameter(name="path", value="/tmp/x")],
                tool_output="File created",
            ),
        ],
        agent_response=AgentResponse(response="Done."),
    )


def test_filter_keeps_only_exact_matching_skill_steps(mock_turn_trace_with_skill):
    validator = CapabilityCompletionValidator(llm_client=AsyncMock())
    filtered = validator.filter_turn_traces_by_expected_skills(
        [mock_turn_trace_with_skill], [SkillCall(skill_id="acme_vendor_onboarding")]
    )
    assert len(filtered) == 1
    assert [step.id for step in filtered[0].steps] == ["skill_step"]


def test_filter_case_insensitive_by_default(mock_turn_trace_with_skill):
    validator = CapabilityCompletionValidator(llm_client=AsyncMock())
    filtered = validator.filter_turn_traces_by_expected_skills(
        [mock_turn_trace_with_skill], [SkillCall(skill_id="ACME_VENDOR_ONBOARDING")]
    )
    assert [step.id for step in filtered[0].steps] == ["skill_step"]


def test_filter_case_sensitive_override_excludes_mismatched_case(mock_turn_trace_with_skill):
    validator = CapabilityCompletionValidator(llm_client=AsyncMock(), config={CASE_SENSITIVE: True})
    filtered = validator.filter_turn_traces_by_expected_skills(
        [mock_turn_trace_with_skill], [SkillCall(skill_id="ACME_VENDOR_ONBOARDING")]
    )
    assert filtered[0].steps == []
    assert not CapabilityCompletionValidator.has_steps(filtered)


def test_filter_trims_whitespace_by_default(mock_turn_trace_with_skill):
    validator = CapabilityCompletionValidator(llm_client=AsyncMock())
    filtered = validator.filter_turn_traces_by_expected_skills(
        [mock_turn_trace_with_skill], [SkillCall(skill_id="  acme_vendor_onboarding  ")]
    )
    assert [step.id for step in filtered[0].steps] == ["skill_step"]


def test_filter_no_match_yields_empty_steps(mock_turn_trace_with_skill):
    validator = CapabilityCompletionValidator(llm_client=AsyncMock())
    filtered = validator.filter_turn_traces_by_expected_skills(
        [mock_turn_trace_with_skill], [SkillCall(skill_id="some_other_skill")]
    )
    assert filtered[0].steps == []
    assert not CapabilityCompletionValidator.has_steps(filtered)


def test_filter_keeps_steps_matching_any_of_multiple_skills(mock_turn_trace_with_skill):
    # OR semantics: the step invokes "acme_vendor_onboarding"; listing it alongside an
    # unrelated skill still keeps the step.
    validator = CapabilityCompletionValidator(llm_client=AsyncMock())
    filtered = validator.filter_turn_traces_by_expected_skills(
        [mock_turn_trace_with_skill],
        [SkillCall(skill_id="some_other_skill"), SkillCall(skill_id="acme_vendor_onboarding")],
    )
    assert [step.id for step in filtered[0].steps] == ["skill_step"]


def test_validate_matching_skill_invokes_judge(mock_turn_trace_with_skill):
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("E", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(
        capability_name="onboard_vendor",
        description="Onboard a vendor.",
        expected_skills=[SkillCall(skill_id="acme_vendor_onboarding")],
    )
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_with_skill], capability))
    assert validation_result.is_completed
    assert (
        validation_result.explanations[0]
        == 'Check: capability "onboard_vendor" has been invoked successfully.'
    )
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_matching_skill_judge_no_match_is_incomplete(mock_turn_trace_with_skill):
    # When the skill matches, the judge is still consulted and its verdict governs:
    # an "N" grade must yield not-completed (distinct from the no-matching-step path).
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("N", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(
        capability_name="onboard_vendor",
        description="Onboard a vendor.",
        expected_skills=[SkillCall(skill_id="acme_vendor_onboarding")],
    )
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_with_skill], capability))
    assert not validation_result.is_completed
    assert (
        validation_result.explanations[0]
        == 'Check: capability "onboard_vendor" has not been invoked.'
    )
    # The judge WAS consulted (unlike the no-matching-step short-circuit).
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_blank_skill_id_skips_filtering(mock_turn_trace_with_skill):
    # A present SkillCall with a blank/whitespace skill_id is treated as "no skill
    # filter": all steps are accounted for and the judge grades the full trace.
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("E", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(
        capability_name="onboard_vendor",
        description="Onboard a vendor.",
        expected_skills=[SkillCall(skill_id="   ")],
    )
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_with_skill], capability))
    assert validation_result.is_completed
    # Judge WAS called (filtering skipped), and it saw the trace's tool call.
    mock_llm_client.make_llm_requests.assert_called_once()
    prompt = mock_llm_client.make_llm_requests.await_args.args[0][0]
    assert "create_file" in prompt


def test_validate_no_matching_skill_returns_incomplete_without_judge(mock_turn_trace_with_skill):
    mock_llm_client = AsyncMock()
    capability = ExpectedCapability(
        capability_name="onboard_vendor",
        description="Onboard a vendor.",
        expected_skills=[SkillCall(skill_id="some_other_skill")],
    )
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_with_skill], capability))
    assert not validation_result.is_completed
    assert validation_result.explanations == [
        "Check: expected capability has not been invoked. "
        'NO_MATCH: no step invoking any of the expected skills ["some_other_skill"] was found.'
    ]
    # The judge must not be called when no matching skill step is found.
    mock_llm_client.make_llm_requests.assert_not_called()


def test_validate_matches_when_only_one_of_multiple_skills_invoked(mock_turn_trace_with_skill):
    # OR semantics through validate(): two expected skills, trace invokes only one →
    # the trace is NOT short-circuited and the judge is consulted.
    mock_llm_client = AsyncMock()

    async def mock_make_llm_requests_fn(prompts):
        if len(prompts) == 5:
            return _judge_responses("E", 5)
        raise AssertionError(f"Expected 5 prompts for judge trials. Got {len(prompts)}")

    mock_llm_client.make_llm_requests.side_effect = mock_make_llm_requests_fn

    capability = ExpectedCapability(
        capability_name="onboard_vendor",
        description="Onboard a vendor.",
        expected_skills=[
            SkillCall(skill_id="acme_vendor_onboarding"),
            SkillCall(skill_id="some_other_skill"),
        ],
    )
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_with_skill], capability))
    assert validation_result.is_completed
    mock_llm_client.make_llm_requests.assert_called_once()


def test_validate_no_match_when_none_of_multiple_skills_invoked(mock_turn_trace_with_skill):
    # OR semantics through validate(): none of the expected skills appear → short-circuit
    # to NO_MATCH, judge not called.
    mock_llm_client = AsyncMock()
    capability = ExpectedCapability(
        capability_name="onboard_vendor",
        description="Onboard a vendor.",
        expected_skills=[
            SkillCall(skill_id="skill_a"),
            SkillCall(skill_id="skill_b"),
        ],
    )
    validator = CapabilityCompletionValidator(llm_client=mock_llm_client)
    validation_result = asyncio.run(validator.validate([mock_turn_trace_with_skill], capability))
    assert not validation_result.is_completed
    assert validation_result.explanations == [
        "Check: expected capability has not been invoked. "
        'NO_MATCH: no step invoking any of the expected skills ["skill_a", "skill_b"] was found.'
    ]
    mock_llm_client.make_llm_requests.assert_not_called()
