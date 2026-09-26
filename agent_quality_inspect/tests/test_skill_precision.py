"""Unit tests for :obj:`SkillPrecisionMetric`.

Precision normalizes the shared intersection numerator over the invocations:
``|S_invoked ∩ S_gt| / |S_invoked|``.
"""

import re

import pytest

from agent_inspect.exception import InvalidInputValueError
from agent_inspect.metrics.constants import CASE_SENSITIVE
from agent_inspect.metrics.scorer import SkillPrecisionMetric
from agent_inspect.metrics.validator.constants import (
    SKILL_ARGUMENT_FAILED_EXACT_MATCH_EXPLANATION,
    SKILL_NAME_MATCHED_EXPLANATION,
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


def test_precision_half_when_one_of_two_invocations_matches():
    # Agent invoked "a" and "b"; only "a" is a ground-truth skill -> 1/2.
    trace = _trace(_step("a"), _step("b"))
    sample = _sample(_skill_call("a"))
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 0.5


def test_precision_one_when_every_invocation_matches():
    trace = _trace(_step("a"), _step("b"))
    sample = _sample(_skill_call("a"), _skill_call("b"))
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 1.0


def test_precision_matches_when_parameters_agree():
    trace = _trace(_step("search", {"q": "cats"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 1.0


def test_precision_misses_when_parameter_value_differs():
    trace = _trace(_step("search", {"q": "dogs"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 0.0


def test_precision_raises_when_no_invocations():
    # No invocations makes precision an undefined 0/0.
    trace = _trace()
    sample = _sample(_skill_call("a"))
    with pytest.raises(InvalidInputValueError, match="Agent trace contains no skill invocations"):
        SkillPrecisionMetric().evaluate(trace, sample)


def test_get_denominator_returns_invocation_count():
    # Precision normalizes over the number of invoked skills.
    metric = SkillPrecisionMetric()
    invocations = [_skill_call("a"), _skill_call("b")]
    assert metric._get_denominator(invocations, _sample(_skill_call("a"))) == 2


def test_get_denominator_raises_when_no_invocations():
    metric = SkillPrecisionMetric()
    with pytest.raises(InvalidInputValueError, match="Agent trace contains no skill invocations"):
        metric._get_denominator([], _sample(_skill_call("a")))


def test_explanations_report_skill_name_matched():
    # Exact-string check, mirroring the validator's explanation tests.
    trace = _trace(_step("a"))
    sample = _sample(_skill_call("a"))
    result = SkillPrecisionMetric().evaluate(trace, sample)
    assert SKILL_NAME_MATCHED_EXPLANATION.format(skill_id="a") in result.explanations


def test_explanations_report_failed_argument_regex():
    # Regex check on the rendered explanation for a mismatched argument value.
    trace = _trace(_step("search", {"q": "dogs"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    result = SkillPrecisionMetric().evaluate(trace, sample)
    expected_line = SKILL_ARGUMENT_FAILED_EXACT_MATCH_EXPLANATION.format(
        param_name="q",
        expected_value="cats",
        expected_type="str",
        actual_value="dogs",
        actual_type="str",
    )
    assert any(re.search(re.escape(expected_line), line) for line in result.explanations)


def test_precision_default_config_is_case_insensitive():
    # Default case_sensitive=False: argument values differing only in case still match.
    trace = _trace(_step("search", {"q": "Cats"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 1.0


def test_precision_default_config_is_trimmed():
    # Default trim=True: surrounding whitespace is stripped before comparison.
    trace = _trace(_step("search", {"q": "  cats  "}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 1.0


def test_precision_case_sensitive_override():
    # Explicit case_sensitive=True: "Cats" and "cats" are treated as different values.
    trace = _trace(_step("search", {"q": "Cats"}))
    sample = _sample(_skill_call("search", {"q": "cats"}))
    assert SkillPrecisionMetric(config={CASE_SENSITIVE: True}).evaluate(trace, sample).score == 0.0
