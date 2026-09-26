import re
from typing import Any, Dict, List, Optional, Tuple

from agent_inspect.exception.error_codes import ErrorCode
from agent_inspect.exception import InvalidInputValueError


def get_config_or_default(config: Optional[Dict[str, Any]], config_key: str, default: Any):
    if config and config_key in config:
        return config[config_key]
    return default


def match_to_grade(completion: str, regex_pattern: str, grade_choices: List[str]):
    """
    Parse a completion string and return binary score based on grade.

    Args:
        completion: The completion string containing a grade
        regex_pattern: Regex pattern to extract the grade
        grade_choices: List of n strings
                        e.g., ["C", "I"] for Complete/Incomplete
                        e.g., ["N", "C", "I"] for Not applicable/Complete/Incomplete

    Returns:
        The matched grade from the grade choices list
    """
    match = re.search(regex_pattern, completion)
    if not match:
        raise InvalidInputValueError(
            internal_code=ErrorCode.INVALID_JUDGE_RESPONSE_FORMAT_ERROR.value,
            message=f"Could not find the judge grade from the completion: {completion}",
        )
    grade = match.group(1).upper()  # Normalize to uppercase for comparison

    for key in grade_choices:
        if grade == key.upper():
            return grade

    raise InvalidInputValueError(
        internal_code=ErrorCode.INVALID_JUDGE_RESPONSE_FORMAT_ERROR.value,
        message=f"Invalid judge grade from the completion: {completion}",
    )


def tally_votes(
    completions: List[str],
    regex_pattern: str,
    grade_counts_with_keys: Dict[str, int],
    invalid_cnt: int,
) -> Tuple[Dict[str, int], int]:
    for completion in completions:
        try:
            grade = match_to_grade(completion, regex_pattern, list(grade_counts_with_keys.keys()))
            grade_counts_with_keys[grade] += 1
        except InvalidInputValueError:
            invalid_cnt += 1
    return grade_counts_with_keys, invalid_cnt
