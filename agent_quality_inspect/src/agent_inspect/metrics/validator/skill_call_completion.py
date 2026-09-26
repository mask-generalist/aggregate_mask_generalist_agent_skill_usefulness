from typing import List, Tuple

from agent_inspect.exception import InvalidInputValueError, ErrorCode
from agent_inspect.metrics.constants import TRIM, CASE_SENSITIVE
from agent_inspect.metrics.validator.constants import (
    SKILL_ARGUMENTS_COUNT_MISMATCH_EXPLANATION,
    SKILL_ARGUMENT_NOT_FOUND_EXPLANATION,
    SKILL_ARGUMENT_FAILED_EXACT_MATCH_EXPLANATION,
    SKILL_ARGUMENT_PASSED_EXACT_MATCH_EXPLANATION,
    SKILL_NOT_FOUND_EXPLANATION,
    SKILL_NAME_MATCHED_EXPLANATION,
    SKILL_ARGUMENTS_PASSED_EXPLANATION,
    SKILL_ARGUMENTS_FAILED_EXPLANATION,
)
from agent_inspect.metrics.validator.exact_match_validator import ExactMatchValidatorAny
from agent_inspect.models.metrics import ValidationResult
from agent_inspect.models.metrics.skill_data_sample import SkillCall, SkillInputParameter


class SkillCallCompletionValidator(ExactMatchValidatorAny):

    def validate(self, candidate: List[SkillCall], ground_truth: SkillCall) -> ValidationResult:

        if not ground_truth:
            raise InvalidInputValueError(
                internal_code=ErrorCode.MISSING_VALUE.value,
                message="No value provided for skill ground truth.",
            )

        if not candidate:
            raise InvalidInputValueError(
                internal_code=ErrorCode.MISSING_VALUE.value,
                message="No value provided for skill candidates.",
            )

        candidate_skill_calls = self._find_skill_calls_with_id(ground_truth.skill_id, candidate)

        if not candidate_skill_calls:
            return ValidationResult(
                is_completed=False,
                explanations=[
                    SKILL_NOT_FOUND_EXPLANATION.format(skill_id=ground_truth.skill_id),
                ],
            )
        if not ground_truth.skill_parameters:
            return ValidationResult(
                is_completed=True,
                explanations=[
                    SKILL_NAME_MATCHED_EXPLANATION.format(skill_id=ground_truth.skill_id)
                ],
            )

        final_explanations: List[str] = []

        for candidate_skill_call in candidate_skill_calls:
            skill_param_match_res, explanations = self._exact_match_skill_input_params(
                candidate_skill_call.skill_parameters or [], ground_truth.skill_parameters
            )
            if skill_param_match_res:
                return ValidationResult(
                    is_completed=True,
                    explanations=[
                        SKILL_ARGUMENTS_PASSED_EXPLANATION.format(skill_id=ground_truth.skill_id),
                        SKILL_NAME_MATCHED_EXPLANATION.format(skill_id=ground_truth.skill_id),
                    ]
                    + explanations,
                )
            final_explanations = explanations

        return ValidationResult(
            is_completed=False,
            explanations=[
                SKILL_ARGUMENTS_FAILED_EXPLANATION.format(skill_id=ground_truth.skill_id),
                SKILL_NAME_MATCHED_EXPLANATION.format(skill_id=ground_truth.skill_id),
            ]
            + final_explanations,
        )

    def _find_skill_calls_with_id(
        self, skill_id: str, candidates: List[SkillCall]
    ) -> List[SkillCall]:
        res_skill_calls = []
        for candidate in candidates:
            if self._exact_match_skill_id(candidate.skill_id, skill_id):
                res_skill_calls.append(candidate)
        return res_skill_calls

    def _exact_match_skill_id(self, candidate: str, ground_truth: str) -> bool:
        return self.exact_match_str(
            candidate,
            ground_truth,
            {
                TRIM: True,
                CASE_SENSITIVE: True,
            },
        )

    def _exact_match_skill_input_params(
        self, candidates: List[SkillInputParameter], ground_truths: List[SkillInputParameter]
    ) -> Tuple[bool, List[str]]:
        if len(candidates) != len(ground_truths):
            return (
                False,
                [
                    SKILL_ARGUMENTS_COUNT_MISMATCH_EXPLANATION.format(
                        expected_count=len(ground_truths), actual_count=len(candidates)
                    )
                ],
            )

        candidates_dict = {}
        explanations = []
        all_matched = True

        for candidate in candidates:
            candidates_dict[
                SkillCallCompletionValidator.format_str(candidate.name, self.config)
            ] = candidate.value

        for ground_truth in ground_truths:
            ground_truth_name = SkillCallCompletionValidator.format_str(
                ground_truth.name, self.config
            )
            if ground_truth_name not in candidates_dict:
                explanations.append(
                    SKILL_ARGUMENT_NOT_FOUND_EXPLANATION.format(param_name=ground_truth.name)
                )
                all_matched = False
                continue

            candidate_value = candidates_dict[ground_truth_name]
            ground_truth_value = ground_truth.value

            exact_match_res = self.exact_match(candidate_value, ground_truth_value, self.config)

            if exact_match_res:
                explanations.append(
                    SKILL_ARGUMENT_PASSED_EXACT_MATCH_EXPLANATION.format(
                        param_name=ground_truth.name,
                    )
                )
            else:
                explanations.append(
                    SKILL_ARGUMENT_FAILED_EXACT_MATCH_EXPLANATION.format(
                        param_name=ground_truth.name,
                        expected_value=ground_truth_value,
                        expected_type=type(ground_truth_value).__name__,
                        actual_value=candidate_value,
                        actual_type=type(candidate_value).__name__,
                    )
                )
                all_matched = False
        return (all_matched, explanations)
