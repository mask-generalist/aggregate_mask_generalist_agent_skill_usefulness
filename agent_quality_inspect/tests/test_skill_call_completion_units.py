"""Per-function unit tests for the exact-match skill validator. Each test targets a
single function so a failure pinpoints the exact function that is incomplete or wrong.

Sections mirror the functions under test, in dependency order:
    ExactMatchValidatorAny.format_str        (normalization: trim / lowercase)
    ExactMatchValidatorAny.exact_match_str   (format_str on both sides, then ==)
    ExactMatchValidatorAny.exact_match       (type-aware comparison)
    SkillCallCompletionValidator._exact_match_skill_id
    SkillCallCompletionValidator._find_skill_calls_with_id   (returns List)
    SkillCallCompletionValidator._exact_match_skill_input_params  (-> (bool, List[str]))
    SkillCallCompletionValidator.validate    (orchestrates all of the above)
"""

import re

import pytest

from agent_inspect.metrics.validator.constants import (
    SKILL_ARGUMENTS_COUNT_MISMATCH_EXPLANATION,
    SKILL_ARGUMENTS_FAILED_EXPLANATION,
    SKILL_ARGUMENTS_PASSED_EXPLANATION,
    SKILL_ARGUMENT_FAILED_EXACT_MATCH_EXPLANATION,
    SKILL_ARGUMENT_NOT_FOUND_EXPLANATION,
    SKILL_ARGUMENT_PASSED_EXACT_MATCH_EXPLANATION,
    SKILL_NAME_MATCHED_EXPLANATION,
    SKILL_NOT_FOUND_EXPLANATION,
)
from agent_inspect.metrics.validator.exact_match_validator import ExactMatchValidatorAny
from agent_inspect.metrics.validator.skill_call_completion import (
    SkillCallCompletionValidator,
)
from agent_inspect.models.metrics.skill_data_sample import SkillCall, SkillInputParameter


@pytest.fixture
def validator():
    return SkillCallCompletionValidator()


def _param(name, value):
    return SkillInputParameter(name=name, value=value)


###############################################################################
# ExactMatchValidatorAny.format_str (static, normalization only)
#   Defaults: trim=True, case_sensitive=True. Never compares; just cleans.
###############################################################################


def test_format_str_trims_by_default():
    assert ExactMatchValidatorAny.format_str("  skill-1  ") == "skill-1"


def test_format_str_trim_disabled_keeps_whitespace():
    assert ExactMatchValidatorAny.format_str("  skill-1  ", {"trim": False}) == "  skill-1  "


def test_format_str_case_preserved_by_default():
    # case_sensitive defaults to False, so casing is lowercased by default.
    assert ExactMatchValidatorAny.format_str("Skill-1") == "skill-1"


def test_format_str_lowercased_when_case_insensitive():
    assert ExactMatchValidatorAny.format_str("Skill-1", {"case_sensitive": False}) == "skill-1"


def test_format_str_trim_and_lowercase_combined():
    assert (
        ExactMatchValidatorAny.format_str("  Skill-1  ", {"trim": True, "case_sensitive": False})
        == "skill-1"
    )


def test_format_str_only_strips_ends_not_interior():
    # trim is .strip() -> ends only; interior whitespace is preserved.
    assert ExactMatchValidatorAny.format_str("  a b  ") == "a b"


###############################################################################
# ExactMatchValidatorAny.exact_match_str  (static)
#   format_str(candidate) == format_str(ground_truth)
###############################################################################


def test_exact_match_str_equal():
    assert ExactMatchValidatorAny.exact_match_str("skill-1", "skill-1") is True


def test_exact_match_str_not_equal():
    assert ExactMatchValidatorAny.exact_match_str("skill-1", "skill-2") is False


def test_exact_match_str_trims_both_sides():
    assert ExactMatchValidatorAny.exact_match_str("skill-1", "\tskill-1\n") is True


def test_exact_match_str_internal_whitespace_is_significant():
    assert ExactMatchValidatorAny.exact_match_str("sk ill", "skill") is False


def test_exact_match_str_trim_disabled_keeps_whitespace():
    assert (
        ExactMatchValidatorAny.exact_match_str("  skill-1  ", "skill-1", {"trim": False}) is False
    )


def test_exact_match_str_case_insensitive_by_default():
    assert ExactMatchValidatorAny.exact_match_str("Skill-1", "skill-1") is True


def test_exact_match_str_case_insensitive_config():
    assert (
        ExactMatchValidatorAny.exact_match_str("Skill-1", "skill-1", {"case_sensitive": False})
        is True
    )


def test_exact_match_str_trim_and_case_insensitive_combined():
    assert (
        ExactMatchValidatorAny.exact_match_str(
            "  Skill-1  ", "skill-1", {"trim": True, "case_sensitive": False}
        )
        is True
    )


###############################################################################
# ExactMatchValidatorAny.exact_match  (static, any type)
#   str vs str -> exact_match_str; otherwise same-type AND ==.
###############################################################################


def test_exact_match_str_values():
    assert ExactMatchValidatorAny.exact_match("a", "a") is True


def test_exact_match_equal_ints():
    assert ExactMatchValidatorAny.exact_match(1, 1) is True


def test_exact_match_different_ints():
    assert ExactMatchValidatorAny.exact_match(1, 2) is False


def test_exact_match_type_mismatch_int_vs_str():
    assert ExactMatchValidatorAny.exact_match(1, "1") is False


def test_exact_match_equal_bools():
    assert ExactMatchValidatorAny.exact_match(True, True) is True


def test_exact_match_bool_vs_int_is_not_type_guarded():
    # bool is a subclass of int, so isinstance(True, int) is True and True == 1.
    # TODO: need to revisit this: is it desirable that bool and int are considered equal?  If not, we need to add a type guard to exact_match.
    assert ExactMatchValidatorAny.exact_match(True, 1) is True


def test_exact_match_none_values_equal():
    assert ExactMatchValidatorAny.exact_match(None, None) is True


def test_exact_match_string_values_still_trim():
    assert ExactMatchValidatorAny.exact_match("  a  ", "a") is True


def test_exact_match_lists_equal_same_order():
    assert ExactMatchValidatorAny.exact_match(["a", "b"], ["a", "b"]) is True


def test_exact_match_lists_differ_by_order():
    assert ExactMatchValidatorAny.exact_match(["a", "b"], ["b", "a"]) is False


###############################################################################
# SkillCallCompletionValidator._exact_match_skill_id
#   Hardcodes trim=True, case_sensitive=True, ignoring self.config.
###############################################################################


def test_exact_match_skill_id_equal(validator):
    assert validator._exact_match_skill_id("skill-1", "skill-1") is True


def test_exact_match_skill_id_not_equal(validator):
    assert validator._exact_match_skill_id("skill-1", "skill-2") is False


def test_exact_match_skill_id_trims_whitespace(validator):
    assert validator._exact_match_skill_id("  skill-1  ", "skill-1") is True


def test_exact_match_skill_id_is_case_sensitive(validator):
    assert validator._exact_match_skill_id("Skill-1", "skill-1") is False


def test_exact_match_skill_id_ignores_case_insensitive_config():
    # id matching hardcodes case_sensitive=True, so config must NOT loosen it.
    v = SkillCallCompletionValidator(config={"case_sensitive": False})
    assert v._exact_match_skill_id("Skill-1", "skill-1") is False


###############################################################################
# SkillCallCompletionValidator._find_skill_calls_with_id  (renamed; returns List)
#   Returns ALL candidates whose id matches, in order.
###############################################################################


def test_find_skill_calls_returns_all_matches(validator):
    c1 = SkillCall(skill_id="skill-1", skill_name="first")
    c2 = SkillCall(skill_id="skill-2")
    c3 = SkillCall(skill_id="skill-1", skill_name="second")
    assert validator._find_skill_calls_with_id("skill-1", [c1, c2, c3]) == [c1, c3]


def test_find_skill_calls_single_match(validator):
    c1 = SkillCall(skill_id="skill-1")
    c2 = SkillCall(skill_id="skill-2")
    assert validator._find_skill_calls_with_id("skill-2", [c1, c2]) == [c2]


def test_find_skill_calls_returns_empty_when_absent(validator):
    c1 = SkillCall(skill_id="skill-1")
    assert validator._find_skill_calls_with_id("skill-9", [c1]) == []


def test_find_skill_calls_empty_candidates(validator):
    assert validator._find_skill_calls_with_id("skill-1", []) == []


def test_find_skill_calls_preserves_order(validator):
    calls = [
        SkillCall(skill_id="a"),
        SkillCall(skill_id="skill-1", skill_name="1st"),
        SkillCall(skill_id="b"),
        SkillCall(skill_id="skill-1", skill_name="2nd"),
    ]
    matched = validator._find_skill_calls_with_id("skill-1", calls)
    assert matched == [calls[1], calls[3]]


def test_find_skill_calls_matches_trimmed_id(validator):
    padded = SkillCall(skill_id="  skill-1  ")
    assert validator._find_skill_calls_with_id("skill-1", [padded]) == [padded]


###############################################################################
# SkillCallCompletionValidator._exact_match_skill_input_params
#   Returns (bool, List[str]). Count check first, then per-parameter checks.
###############################################################################


def test_params_match_all_equal(validator):
    cand = [_param("a", "1")]
    gt = [_param("a", "1")]
    ok, explanations = validator._exact_match_skill_input_params(cand, gt)
    assert ok is True
    assert isinstance(explanations, list)


def test_params_length_mismatch_fails(validator):
    cand = [_param("a", "1")]
    gt = [_param("a", "1"), _param("b", "2")]
    ok, explanations = validator._exact_match_skill_input_params(cand, gt)
    assert ok is False
    assert isinstance(explanations, list) and explanations


def test_params_value_mismatch_fails(validator):
    cand = [_param("a", "1")]
    gt = [_param("a", "2")]
    ok, _ = validator._exact_match_skill_input_params(cand, gt)
    assert ok is False


def test_params_value_whitespace_trimmed(validator):
    cand = [_param("a", "  1  ")]
    gt = [_param("a", "1")]
    ok, _ = validator._exact_match_skill_input_params(cand, gt)
    assert ok is True


def test_params_value_case_insensitive_by_default_matches(validator):
    cand = [_param("a", "Yes")]
    gt = [_param("a", "yes")]
    ok, _ = validator._exact_match_skill_input_params(cand, gt)
    assert ok is True


def test_params_value_case_insensitive_via_config():
    v = SkillCallCompletionValidator(config={"case_sensitive": False})
    cand = [_param("a", "Yes")]
    gt = [_param("a", "yes")]
    ok, _ = v._exact_match_skill_input_params(cand, gt)
    assert ok is True


def test_params_multiple_all_match(validator):
    # Two parameters both match -> success, exercising the loop across more than
    # one parameter (the single-param success case can't).
    cand = [_param("a", "1"), _param("b", "2")]
    gt = [_param("a", "1"), _param("b", "2")]
    ok, explanations = validator._exact_match_skill_input_params(cand, gt)
    assert ok is True
    assert isinstance(explanations, list) and explanations


def test_params_first_fails_second_matches(validator):
    # First parameter mismatches, second matches -> overall must be False.
    # Complements test_params_all_must_match_not_just_first (which fails on the
    # second): confirms the result is independent of *which* parameter fails.
    cand = [_param("a", "WRONG"), _param("b", "2")]
    gt = [_param("a", "1"), _param("b", "2")]
    ok, _ = validator._exact_match_skill_input_params(cand, gt)
    assert ok is False


def test_params_name_mismatch_fails(validator):
    # Same value, different candidate parameter name -> must fail.
    # Regression guard: candidate names must actually be compared (the dict is
    # built from candidates, not ground truths).
    cand = [_param("wrong-name", "1")]
    gt = [_param("a", "1")]
    ok, _ = validator._exact_match_skill_input_params(cand, gt)
    assert ok is False


def test_params_all_must_match_not_just_first(validator):
    # Two params: first matches, second does not -> overall must be False.
    # Regression guard: success must require *all* params to match, not return
    # early after the first matching one.
    cand = [_param("a", "1"), _param("b", "WRONG")]
    gt = [_param("a", "1"), _param("b", "2")]
    ok, _ = validator._exact_match_skill_input_params(cand, gt)
    assert ok is False


###############################################################################
# SkillCallCompletionValidator.validate  (orchestration)
###############################################################################


def test_validate_skill_never_called(validator):
    result = validator.validate([SkillCall(skill_id="skill-9")], SkillCall(skill_id="skill-1"))
    assert result.is_completed is False


def test_validate_empty_candidates_raises(validator):
    # Empty candidates is treated as invalid input and raises, distinct from a
    # non-empty list that simply doesn't contain the expected skill.
    from agent_inspect.exception import InvalidInputValueError

    with pytest.raises(InvalidInputValueError):
        validator.validate([], SkillCall(skill_id="skill-1"))


def test_validate_skill_matched_no_params(validator):
    # Matching id, ground truth has no params -> early success.
    result = validator.validate([SkillCall(skill_id="skill-1")], SkillCall(skill_id="skill-1"))
    assert result.is_completed is True


def test_validate_skill_matched_with_params(validator):
    params = [_param("a", "1")]
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=params)],
        SkillCall(skill_id="skill-1", skill_parameters=params),
    )
    assert result.is_completed is True


def test_validate_skill_matched_but_params_fail(validator):
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")])],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "2")]),
    )
    assert result.is_completed is False


def test_validate_first_candidate_wrong_second_right(validator):
    # The improvement in this rewrite: all candidates sharing the id are tried,
    # so a correct later invocation still yields success.
    result = validator.validate(
        [
            SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "WRONG")]),
            SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")]),
        ],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")]),
    )
    assert result.is_completed is True


def test_validate_none_ground_truth_raises(validator):
    # validate guards against a falsy ground truth by raising.
    from agent_inspect.exception import InvalidInputValueError

    with pytest.raises(InvalidInputValueError):
        validator.validate([SkillCall(skill_id="skill-1")], None)


###############################################################################
# SkillCallCompletionValidator.validate  (explanation strings)
#   validate has no separate "explanation" method: it builds the
#   ValidationResult.explanations list inline from the constants in
#   validator/constants.py. These tests assert that list -- both the exact
#   lines (via the imported constants, so wording changes stay in one place)
#   and, for the lines carrying dynamic fields, a regex on the rendered text.
###############################################################################


def test_explanation_skill_not_found_line(validator):
    # Unmatched id -> a single SKILL_NOT_FOUND line naming the expected id.
    result = validator.validate([SkillCall(skill_id="skill-9")], SkillCall(skill_id="skill-1"))
    assert result.explanations == [SKILL_NOT_FOUND_EXPLANATION.format(skill_id="skill-1")]


def test_explanation_skill_not_found_regex(validator):
    # The rendered line embeds the expected id between quotes.
    result = validator.validate([SkillCall(skill_id="skill-9")], SkillCall(skill_id="skill-1"))
    assert re.search(r'No matching skill id "skill-1" is found', result.explanations[0])


def test_explanation_name_only_match_line(validator):
    # Id matches and ground truth has no params -> just the name-matched line.
    result = validator.validate([SkillCall(skill_id="skill-1")], SkillCall(skill_id="skill-1"))
    assert result.explanations == [SKILL_NAME_MATCHED_EXPLANATION.format(skill_id="skill-1")]


def test_explanation_params_passed_lines(validator):
    # All params match -> arguments-passed header, name-matched, then one
    # per-parameter passed line, in that order.
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")])],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")]),
    )
    assert result.explanations == [
        SKILL_ARGUMENTS_PASSED_EXPLANATION.format(skill_id="skill-1"),
        SKILL_NAME_MATCHED_EXPLANATION.format(skill_id="skill-1"),
        SKILL_ARGUMENT_PASSED_EXACT_MATCH_EXPLANATION.format(param_name="a"),
    ]


def test_explanation_params_failed_value_lines(validator):
    # Wrong value -> arguments-failed header, name-matched, then the per-param
    # failed line carrying expected/actual value and type.
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")])],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "2")]),
    )
    assert result.explanations[0] == SKILL_ARGUMENTS_FAILED_EXPLANATION.format(skill_id="skill-1")
    assert result.explanations[1] == SKILL_NAME_MATCHED_EXPLANATION.format(skill_id="skill-1")
    assert result.explanations[2] == SKILL_ARGUMENT_FAILED_EXACT_MATCH_EXPLANATION.format(
        param_name="a",
        expected_value="2",
        expected_type="str",
        actual_value="1",
        actual_type="str",
    )


def test_explanation_params_failed_value_regex(validator):
    # The dynamic failed-argument line reports both values and their types.
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")])],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "2")]),
    )
    assert re.search(
        r'Argument "a" has failed exact match\. '
        r"Expected value: 2, Expected type: str\. "
        r"Actual value: 1, Actual type: str\.",
        result.explanations[2],
    )


def test_explanation_count_mismatch_line(validator):
    # Fewer candidate params than expected -> the count-mismatch line reports
    # both counts.
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")])],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1"), _param("b", "2")]),
    )
    assert result.explanations[2] == SKILL_ARGUMENTS_COUNT_MISMATCH_EXPLANATION.format(
        expected_count=2, actual_count=1
    )
    assert re.search(r"Expected 2 arguments, but found 1 arguments\.", result.explanations[2])


def test_explanation_param_name_not_found_line(validator):
    # Expected param name absent from the candidate -> the not-found line names
    # the missing parameter.
    result = validator.validate(
        [SkillCall(skill_id="skill-1", skill_parameters=[_param("x", "1")])],
        SkillCall(skill_id="skill-1", skill_parameters=[_param("a", "1")]),
    )
    assert result.explanations[2] == SKILL_ARGUMENT_NOT_FOUND_EXPLANATION.format(param_name="a")
    assert re.search(r'Argument "a" not even found in actual skill call\.', result.explanations[2])
