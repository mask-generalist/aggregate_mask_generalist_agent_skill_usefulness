from agent_inspect.core.utils import (
    get_config_or_default,
    tally_votes,
)
from agent_inspect.metrics.constants import (
    COMPLETE_INCOMPLETE_DICT,
    COMPLETE_INCOMPLETE_GRADE_PATTERN,
)


def test_config_or_default_returns_config_value_when_key_exists():
    config = {"key1": "value1", "key2": "value2"}
    result = get_config_or_default(config, "key1", "default_value")
    assert result == "value1"


def test_config_or_default_returns_default_when_key_does_not_exist():
    config = {"key1": "value1"}
    result = get_config_or_default(config, "key2", "default_value")
    assert result == "default_value"


def test_tally_votes_counts_complete_incomplete_and_invalid():
    completions = ["Grade: C", "Grade: I", "Grade: C", "Invalid Grade"]
    grade_count_with_keys = {key: 0 for key in COMPLETE_INCOMPLETE_DICT.keys()}

    grade_counts, invalid_cnt = tally_votes(
        completions=completions,
        regex_pattern=COMPLETE_INCOMPLETE_GRADE_PATTERN,
        grade_counts_with_keys=grade_count_with_keys,
        invalid_cnt=0,
    )
    assert grade_counts["C"] == 2
    assert grade_counts["I"] == 1
    assert invalid_cnt == 1


def test_tally_votes_with_existing_counts():
    completions = ["Grade: C", "Grade: I"]
    grade_count_with_keys = {key: 0 for key in COMPLETE_INCOMPLETE_DICT.keys()}
    grade_count_with_keys["C"] = 5
    grade_count_with_keys["I"] = 3
    invalid_cnt = 2

    grade_counts, invalid_cnt = tally_votes(
        completions=completions,
        regex_pattern=COMPLETE_INCOMPLETE_GRADE_PATTERN,
        grade_counts_with_keys=grade_count_with_keys,
        invalid_cnt=invalid_cnt,
    )
    assert grade_counts["C"] == 6
    assert grade_counts["I"] == 4
    assert invalid_cnt == 2
