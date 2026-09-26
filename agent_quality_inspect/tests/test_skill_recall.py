"""Unit tests for :obj:`SkillRecallMetric`.

Recall normalizes the shared intersection numerator over the ground truth:
``|S_invoked ∩ S_gt| / |S_gt|``.
"""

import re

import pytest

from agent_inspect.exception import InvalidInputValueError
from agent_inspect.metrics.constants import CASE_SENSITIVE
from agent_inspect.metrics.scorer import SkillRecallMetric
from agent_inspect.metrics.validator.constants import (
    SKILL_NAME_MATCHED_EXPLANATION,
    SKILL_NOT_FOUND_EXPLANATION,
)
from agent_inspect.models.metrics.agent_data_sample import EvaluationSample, SubGoal
from agent_inspect.models.metrics.agent_trace import AgentDialogueTrace, Step, TurnTrace
from agent_inspect.models.metrics.skill_data_sample import SkillCall, SkillInputParameter


def _skill_call(skill_id, params=None):
    skill_parameters = (
        [SkillInputParameter(name=n, value=v) for n, v in params.items()] if params else None
    )
    return SkillCall(skill_id=skill_id, skill_parameters=skill_parameters)


def _step(skill_id, params=None):
    """A single invoked skill: a trace step carrying a ``skill_call``."""
    return Step(id=skill_id, parent_ids=[], skill_calls=[_skill_call(skill_id, params)])


def _trace(*steps):
    """A one-turn trace built from the given steps (pass none for an empty turn)."""
    return AgentDialogueTrace(turns=[TurnTrace(id="t1", agent_input="hi", steps=list(steps))])


def _sample(*expected_skill_calls):
    return EvaluationSample(
        sub_goals=[SubGoal(details="done")],
        expected_skill_calls=list(expected_skill_calls),
    )


def test_recall_half_when_one_of_two_expected_satisfied():
    # Expected "a" and "b"; agent invoked only "a" -> 1/2.
    trace = _trace(_step("a"))
    sample = _sample(_skill_call("a"), _skill_call("b"))
    assert SkillRecallMetric().evaluate(trace, sample).score == 0.5


def test_recall_zero_when_no_invocations():
    # Well defined at 0.0 (unlike precision) even with no invocations.
    trace = _trace()
    sample = _sample(_skill_call("a"))
    assert SkillRecallMetric().evaluate(trace, sample).score == 0.0


def test_recall_matches_when_parameters_agree():
    trace = _trace(_step("search", {"q": "cats"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillRecallMetric().evaluate(trace, sample).score == 1.0


def test_recall_misses_when_parameter_value_differs():
    trace = _trace(_step("search", {"q": "dogs"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillRecallMetric().evaluate(trace, sample).score == 0.0


def test_get_denominator_returns_expected_count():
    # Recall normalizes over the number of ground-truth skills, regardless of
    # what the agent invoked.
    metric = SkillRecallMetric()
    sample = _sample(_skill_call("a"), _skill_call("b"))
    assert metric._get_denominator([], sample) == 2


def test_get_denominator_raises_when_no_expected_skill_calls():
    metric = SkillRecallMetric()
    with pytest.raises(InvalidInputValueError, match="No expected skill calls"):
        metric._get_denominator([], _sample())


def test_explanations_report_skill_name_matched():
    # Exact-string check, mirroring the validator's explanation tests.
    trace = _trace(_step("a"))
    sample = _sample(_skill_call("a"))
    result = SkillRecallMetric().evaluate(trace, sample)
    assert SKILL_NAME_MATCHED_EXPLANATION.format(skill_id="a") in result.explanations


def test_explanations_report_skill_not_found_regex():
    # Regex check: expected "b" was never invoked, so its not-found line appears.
    trace = _trace(_step("a"))
    sample = _sample(_skill_call("a"), _skill_call("b"))
    result = SkillRecallMetric().evaluate(trace, sample)
    expected_line = SKILL_NOT_FOUND_EXPLANATION.format(skill_id="b")
    assert any(re.search(re.escape(expected_line), line) for line in result.explanations)


def test_recall_default_config_is_case_insensitive():
    # Default case_sensitive=False: argument values differing only in case still match.
    trace = _trace(_step("search", {"q": "Cats"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillRecallMetric().evaluate(trace, sample).score == 1.0


def test_recall_default_config_is_trimmed():
    # Default trim=True: surrounding whitespace is stripped before comparison.
    trace = _trace(_step("search", {"q": "  cats  "}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillRecallMetric().evaluate(trace, sample).score == 1.0


def test_recall_case_sensitive_override():
    # Explicit case_sensitive=True: "Cats" and "cats" are treated as different values.
    trace = _trace(_step("search", {"q": "Cats"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillRecallMetric(config={CASE_SENSITIVE: True}).evaluate(trace, sample).score == 0.0
