from typing import Optional, Dict, Any, List, Tuple

from agent_inspect.core.utils import tally_votes, get_config_or_default, match_to_grade

from agent_inspect.metrics.constants import (
    STATUS_200,
    OPTIMIZE_JUDGE_TRIALS,
    MAX_RETRY_JUDGE_TRIALS,
    MAX_RETRY_JUDGE_TRIALS_DEFAULT,
    NUM_JUDGE_TRIALS,
    NUM_JUDGE_TRIALS_DEFAULT,
    COULD_NOT_REACH_MAJORITY_DECISION,
    COMPLETE_INCOMPLETE_GRADE_PATTERN,
    COMPLETE_INCOMPLETE_DICT,
)

from agent_inspect.exception.error_codes import ErrorCode

from agent_inspect.exception import EvaluationError, InvalidInputValueError
from agent_inspect.metrics.validator.validator import Validator


from agent_inspect.clients.llm_client import LLMClient
from agent_inspect.models.llm_response import LLMResponse


class LLMValidator(Validator):

    def __init__(self, llm_client: LLMClient, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.llm_client = llm_client

    async def get_majority_voted_score_from_judge_responses(
        self,
        prompt: str,
        regex_pattern: str = COMPLETE_INCOMPLETE_GRADE_PATTERN,
        grade_choices_key_value_pair: Dict[str, int] = COMPLETE_INCOMPLETE_DICT,
    ) -> Tuple[int, List[str]]:
        if len(grade_choices_key_value_pair) > 3:
            raise InvalidInputValueError(
                internal_code=ErrorCode.INVALID_VALUE.value,
                message=(
                    f"grade_choices supports at most 3 grades; got "
                    f"{len(grade_choices_key_value_pair)}."
                ),
            )

        optimize_judge_trials = get_config_or_default(
            config=self.config, config_key=OPTIMIZE_JUDGE_TRIALS, default=False
        )
        max_retry_judge_trials = get_config_or_default(
            config=self.config,
            config_key=MAX_RETRY_JUDGE_TRIALS,
            default=MAX_RETRY_JUDGE_TRIALS_DEFAULT,
        )
        num_judge_trials = get_config_or_default(
            config=self.config,
            config_key=NUM_JUDGE_TRIALS,
            default=NUM_JUDGE_TRIALS_DEFAULT,
        )

        if optimize_judge_trials:
            return await LLMValidator.get_majority_voted_score_from_judge_responses_optimised(
                self.llm_client,
                prompt,
                num_judge_trials,
                regex_pattern,
                grade_choices_key_value_pair,
            )
        else:
            return await LLMValidator.get_majority_voted_score_from_judge_responses_unoptimised(
                self.llm_client,
                prompt,
                num_judge_trials,
                max_retry_judge_trials,
                regex_pattern,
                grade_choices_key_value_pair,
            )

    @staticmethod
    async def get_majority_voted_score_from_judge_responses_unoptimised(
        llm_client: LLMClient,
        prompt: str,
        no_of_trials: int,
        max_retry_judge_trials: int,
        regex_pattern: str = COMPLETE_INCOMPLETE_GRADE_PATTERN,
        grade_choices_key_value_pair: Dict[str, int] = COMPLETE_INCOMPLETE_DICT,
    ) -> Tuple[int, List[str]]:
        LLMValidator._validate_judge_trials(no_of_trials)
        judge_explanations = []
        prompts = [prompt] * no_of_trials
        judge_responses = await llm_client.make_llm_requests(prompts)
        judge_explanations.extend(
            LLMValidator._get_judge_explanations_from_responses(
                judge_responses, regex_pattern, list(grade_choices_key_value_pair.keys())
            )
        )
        grade_counts_with_keys = {grade: 0 for grade in list(grade_choices_key_value_pair.keys())}

        grade_counts_with_keys, invalid_trial_count = LLMValidator._tally_judge_voting(
            judge_responses=judge_responses,
            regex_pattern=regex_pattern,
            grade_counts_with_key=grade_counts_with_keys,
        )

        retry_attempts = 0
        while invalid_trial_count > 0 and retry_attempts < max_retry_judge_trials:
            retry_prompts = [prompt] * invalid_trial_count
            retry_responses = await llm_client.make_llm_requests(retry_prompts)
            judge_explanations.extend(
                LLMValidator._get_judge_explanations_from_responses(
                    retry_responses, regex_pattern, list(grade_choices_key_value_pair.keys())
                )
            )
            grade_counts_with_keys, new_invalid = LLMValidator._tally_judge_voting(
                judge_responses=retry_responses,
                regex_pattern=regex_pattern,
                grade_counts_with_key=grade_counts_with_keys,
            )
            invalid_trial_count = new_invalid
            retry_attempts += 1

        if invalid_trial_count > 0:
            raise EvaluationError(
                internal_code=ErrorCode.INVALID_LLM_JUDGE_RESULT_ERROR.value,
                message="One or more judge trials returned invalid responses after retries.",
            )
        threshold = (no_of_trials // 2) + 1
        potential_winner = LLMValidator.get_grades_exceeding_threshold(
            grade_counts_with_key=grade_counts_with_keys, threshold=threshold
        )
        if potential_winner:
            return grade_choices_key_value_pair[potential_winner], judge_explanations

        pre_tiebreak_counts = dict(grade_counts_with_keys)

        last_try_responses = await llm_client.make_llm_requests([prompt])

        grade_counts_with_keys, new_invalid = LLMValidator._tally_judge_voting(
            judge_responses=last_try_responses,
            regex_pattern=regex_pattern,
            grade_counts_with_key=grade_counts_with_keys,
        )
        if new_invalid > 0:
            raise EvaluationError(
                internal_code=ErrorCode.INVALID_LLM_JUDGE_RESULT_ERROR.value,
                message="During tiebreaking, one or more judge trials returned invalid responses.",
            )

        tiebreak_winner = LLMValidator.get_grades_exceeding_threshold(
            grade_counts_with_key=grade_counts_with_keys, threshold=threshold
        )
        if tiebreak_winner:
            judge_explanations = LLMValidator._replace_least_voted_explanation_with_tiebreak(
                judge_explanations=judge_explanations,
                pre_tiebreak_counts=pre_tiebreak_counts,
                tiebreak_responses=last_try_responses,
                regex_pattern=regex_pattern,
                grade_choices=list(grade_choices_key_value_pair.keys()),
            )
            return grade_choices_key_value_pair[tiebreak_winner], judge_explanations

        raise EvaluationError(
            internal_code=ErrorCode.INSUFFICIENT_JUDGE_RESPONSES_ERROR.value,
            message=COULD_NOT_REACH_MAJORITY_DECISION,
        )

    @staticmethod
    async def get_majority_voted_score_from_judge_responses_optimised(
        llm_client: LLMClient,
        prompt: str,
        no_of_trials: int,
        regex_pattern: str = COMPLETE_INCOMPLETE_GRADE_PATTERN,
        grade_choices_key_value_pair: Dict[str, int] = COMPLETE_INCOMPLETE_DICT,
    ) -> Tuple[int, List[str]]:
        LLMValidator._validate_judge_trials(no_of_trials)
        judge_explanations = []
        threshold = (no_of_trials // 2) + 1

        first_wave = min(threshold, no_of_trials)
        judge_responses = await llm_client.make_llm_requests([prompt] * first_wave)
        judge_explanations.extend(
            LLMValidator._get_judge_explanations_from_responses(
                judge_responses=judge_responses,
                regex_pattern=regex_pattern,
                grade_choices=list(grade_choices_key_value_pair.keys()),
            )
        )
        grade_counts_with_keys = {grade: 0 for grade in list(grade_choices_key_value_pair.keys())}
        grade_counts_with_keys, invalid_trial_count = LLMValidator._tally_judge_voting(
            judge_responses=judge_responses,
            regex_pattern=regex_pattern,
            grade_counts_with_key=grade_counts_with_keys,
        )

        processed = first_wave
        potential_winner = LLMValidator.get_grades_exceeding_threshold(
            grade_counts_with_key=grade_counts_with_keys, threshold=threshold
        )
        if potential_winner:
            return grade_choices_key_value_pair[potential_winner], judge_explanations

        while processed < no_of_trials:
            remaining = no_of_trials - processed
            if not any(cnt + remaining >= threshold for cnt in grade_counts_with_keys.values()):
                raise EvaluationError(
                    internal_code=ErrorCode.INSUFFICIENT_JUDGE_RESPONSES_ERROR.value,
                    message=COULD_NOT_REACH_MAJORITY_DECISION,
                )

            wave = min(
                remaining, min(max(0, threshold - cnt) for cnt in grade_counts_with_keys.values())
            )
            prompts = [prompt] * wave
            judge_responses = await llm_client.make_llm_requests(prompts)
            judge_explanations.extend(
                LLMValidator._get_judge_explanations_from_responses(
                    judge_responses=judge_responses,
                    regex_pattern=regex_pattern,
                    grade_choices=list(grade_choices_key_value_pair.keys()),
                )
            )
            grade_counts_with_keys, new_invalid_trial_count = LLMValidator._tally_judge_voting(
                judge_responses=judge_responses,
                regex_pattern=regex_pattern,
                grade_counts_with_key=grade_counts_with_keys,
            )
            invalid_trial_count += new_invalid_trial_count
            processed += wave
            potential_winner = LLMValidator.get_grades_exceeding_threshold(
                grade_counts_with_key=grade_counts_with_keys, threshold=threshold
            )
            if potential_winner:
                return grade_choices_key_value_pair[potential_winner], judge_explanations

        raise EvaluationError(
            internal_code=ErrorCode.INSUFFICIENT_JUDGE_RESPONSES_ERROR.value,
            message=COULD_NOT_REACH_MAJORITY_DECISION,
        )

    @staticmethod
    def _tally_judge_voting(
        regex_pattern: str,
        judge_responses: List[LLMResponse],
        grade_counts_with_key: Dict[str, int],
    ):
        completions = []
        invalid_cnt = 0
        for judge_response in judge_responses:
            if (
                judge_response.status != STATUS_200
                or not judge_response.completion
                or not judge_response.completion.strip()
            ):
                invalid_cnt += 1
            else:
                completions.append(judge_response.completion)

        grade_counts_with_key, invalid_cnt = tally_votes(
            completions=completions,
            regex_pattern=regex_pattern,
            grade_counts_with_keys=grade_counts_with_key,
            invalid_cnt=invalid_cnt,
        )
        return grade_counts_with_key, invalid_cnt

    @staticmethod
    def _get_judge_explanations_from_responses(
        judge_responses: List[LLMResponse],
        regex_pattern: str,
        grade_choices: List[str],
    ) -> List[str]:
        res_success_explanations = [
            response.completion
            for response in judge_responses
            if response.status == STATUS_200 and response.completion
        ]
        valid_explanations = []
        for explanation in res_success_explanations:
            try:
                match_to_grade(explanation, regex_pattern, grade_choices)
            except InvalidInputValueError:
                continue
            valid_explanations.append(explanation)
        return valid_explanations

    @staticmethod
    def _validate_judge_trials(no_of_trials: int) -> None:
        if no_of_trials <= 0 or no_of_trials % 2 == 0:
            raise EvaluationError(
                internal_code=ErrorCode.INVALID_LLM_JUDGE_RESULT_ERROR.value,
                message="Number of judge trials must be a positive odd integer.",
            )

    @staticmethod
    def get_grades_exceeding_threshold(
        grade_counts_with_key: Dict[str, int], threshold: int
    ) -> Optional[str]:
        exceeding = [grade for grade, count in grade_counts_with_key.items() if count >= threshold]

        if len(exceeding) > 2:
            raise EvaluationError(
                internal_code=ErrorCode.INSUFFICIENT_JUDGE_RESPONSES_ERROR.value,
                message=f"More than 2 grades exceed the threshold ({threshold}): {exceeding}",
            )

        return exceeding[0] if exceeding else None

    @staticmethod
    def _replace_least_voted_explanation_with_tiebreak(
        judge_explanations: List[str],
        pre_tiebreak_counts: Dict[str, int],
        tiebreak_responses: List[LLMResponse],
        regex_pattern: str,
        grade_choices: List[str],
    ) -> List[str]:
        tiebreak_explanations = LLMValidator._get_judge_explanations_from_responses(
            judge_responses=tiebreak_responses,
            regex_pattern=regex_pattern,
            grade_choices=grade_choices,
        )

        voted_grades = {g: c for g, c in pre_tiebreak_counts.items() if c > 0}
        judge_explanation_copy = list(judge_explanations)
        least_voted_grade = min(
            voted_grades, key=lambda g: (voted_grades[g], grade_choices.index(g))
        )
        for idx, explanation in enumerate(judge_explanation_copy):
            try:
                matched_grade = match_to_grade(explanation, regex_pattern, grade_choices)
            except InvalidInputValueError:
                continue
            if matched_grade == least_voted_grade:
                judge_explanation_copy.pop(idx)
                break

        judge_explanation_copy.extend(tiebreak_explanations)
        return judge_explanation_copy
