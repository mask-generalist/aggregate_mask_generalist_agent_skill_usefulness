from typing import List, Optional, Dict, Any
from dataclasses import replace

from agent_inspect.clients.llm_client import LLMClient
from agent_inspect.metrics.constants import (
    INCLUDE_JUDGE_EXPLANATION,
    INCLUDE_PROMPT_SENT_TO_LLMJ,
    EXACT_FUZZY_NO_MATCH_GRADE_PATTERN,
    EXACT_FUZZY_NO_MATCH_DICT,
)
from agent_inspect.metrics.validator.templates import (
    DEFAULT_CAPABILITY_COMPLETION_TEMPLATE,
)
from agent_inspect.models.metrics.capability_data_sample import ExpectedCapability
from agent_inspect.models.metrics.agent_trace import TurnTrace, Step
from agent_inspect.models.metrics.skill_data_sample import SkillCall
from agent_inspect.models.metrics.validation_result import CapabilityValidationResult
from agent_inspect.core.utils import get_config_or_default
from agent_inspect.metrics.utils.capability_validators import ExpectedCapabilityValidator
from agent_inspect.metrics.utils.trace_validators import TraceValidator
from agent_inspect.metrics.validator.exact_match_validator import ExactMatchValidatorAny
from agent_inspect.metrics.validator.llm_validator import LLMValidator


class CapabilityCompletionValidator(LLMValidator):

    def __init__(self, llm_client: LLMClient, config: Optional[Dict[str, Any]] = None):
        super().__init__(llm_client, config)

    async def validate(
        self, turn_traces: List[TurnTrace], expected_capability: ExpectedCapability, **kwargs
    ) -> CapabilityValidationResult:

        TraceValidator.validate_agent_trace_if_empty(turn_traces)
        ExpectedCapabilityValidator.validate_expected_capability(expected_capability)

        include_judge_explanation = get_config_or_default(
            config=self.config, config_key=INCLUDE_JUDGE_EXPLANATION, default=False
        )
        include_entire_prompt_in_validation_result = get_config_or_default(
            config=self.config, config_key=INCLUDE_PROMPT_SENT_TO_LLMJ, default=False
        )

        expected_skills = [
            skill for skill in (expected_capability.expected_skills or []) if skill.skill_id.strip()
        ]
        if expected_skills:
            turn_traces = self.filter_turn_traces_by_expected_skills(turn_traces, expected_skills)
            if not self.has_steps(turn_traces):
                skill_ids = ", ".join(f'"{skill.skill_id}"' for skill in expected_skills)
                return CapabilityValidationResult(
                    is_completed=False,
                    expected_capability=expected_capability,
                    explanations=[
                        f"Check: expected capability has not been invoked. "
                        f"NO_MATCH: no step invoking any of the expected skills [{skill_ids}] was found."
                    ],
                )

        prompt = self.generate_prompt_from_capability_and_turn_traces(
            expected_capability, turn_traces
        )
        (
            majority_voted_score,
            judge_explanations,
        ) = await self.get_majority_voted_score_from_judge_responses(
            prompt=prompt,
            regex_pattern=EXACT_FUZZY_NO_MATCH_GRADE_PATTERN,
            grade_choices_key_value_pair=EXACT_FUZZY_NO_MATCH_DICT,
        )

        is_completed = True if majority_voted_score == 1 else False
        capability_name = expected_capability.capability_name
        explanations = []
        if is_completed:
            if capability_name and capability_name.strip():
                explanations.append(
                    f'Check: capability "{capability_name}" has been invoked successfully.'
                )
            else:
                explanations.append(
                    f"Check: capability with the description "
                    f'"{expected_capability.description}" has been invoked successfully.'
                )
        else:
            if capability_name and capability_name.strip():
                explanations.append(f'Check: capability "{capability_name}" has not been invoked.')
            else:
                explanations.append(
                    f"Check: capability with the description "
                    f'"{expected_capability.description}" has not been invoked.'
                )
        if include_judge_explanation:
            explanations.extend(judge_explanations)

        if include_entire_prompt_in_validation_result:
            return CapabilityValidationResult(
                is_completed=is_completed,
                expected_capability=expected_capability,
                explanations=explanations,
                prompt_sent_to_llmj=prompt,
            )
        return CapabilityValidationResult(
            is_completed=is_completed,
            expected_capability=expected_capability,
            explanations=explanations,
        )

    @staticmethod
    def format_expected_output(expected_capability: ExpectedCapability) -> str:
        expected_output = expected_capability.expected_output
        if expected_output is None:
            return "No expected output specified."
        return f"Expected value: {expected_output.check}"

    def filter_turn_traces_by_expected_skills(
        self, turn_traces: List[TurnTrace], expected_skills: List[SkillCall]
    ) -> List[TurnTrace]:
        filtered_turns: List[TurnTrace] = []
        for turn in turn_traces:
            matching_steps: List[Step] = []
            for step in turn.steps or []:
                if any(
                    ExactMatchValidatorAny.exact_match_str(
                        skill_call.skill_id, expected_skill.skill_id, self.config
                    )
                    for skill_call in step.skill_calls or []
                    for expected_skill in expected_skills
                ):
                    matching_steps.append(step)
            filtered_turns.append(replace(turn, steps=matching_steps))
        return filtered_turns

    @staticmethod
    def has_steps(turn_traces: List[TurnTrace]) -> bool:
        return any(turn.steps for turn in turn_traces)

    @staticmethod
    def format_tool_call_steps_str(turn_traces: List[TurnTrace]) -> str:
        tool_call_strs: list[str] = []
        for turn in turn_traces:
            if not turn.steps:
                continue
            for step in turn.steps:
                if not step.tool:
                    continue
                tool_input_args = {}
                if step.tool_input_args:
                    for tool_input_parameter in step.tool_input_args:
                        tool_input_args[tool_input_parameter.name] = tool_input_parameter.value
                tool_call_strs.append(
                    str(
                        {
                            "id": step.id,
                            "parent_ids": step.parent_ids,
                            "type": "Tool Call",
                            "content": {
                                "tool_name": step.tool,
                                "tool_arguments": tool_input_args,
                                "tool_output": step.tool_output,
                            },
                        }
                    )
                )
        return "\n".join(tool_call_strs) if tool_call_strs else "None"

    @staticmethod
    def generate_prompt_from_capability_and_turn_traces(
        expected_capability: ExpectedCapability, turn_traces: List[TurnTrace]
    ) -> str:
        return DEFAULT_CAPABILITY_COMPLETION_TEMPLATE.format(
            tool_call_steps=CapabilityCompletionValidator.format_tool_call_steps_str(turn_traces),
            capability_name=expected_capability.capability_name or "Not specified",
            capability_description=expected_capability.description,
            expected_output=CapabilityCompletionValidator.format_expected_output(
                expected_capability
            ),
        )
