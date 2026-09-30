"""The ``model_builder`` seam and the scripted builders that fill it (Approach 1's D16; plan Iteration 7).

Iteration 2 deferred Approach 1's ``ModelBuilder`` and ``scripted_model_builder``, because both lived beside its
orchestrator. Iteration 7 restores them: the protocol moves to :mod:`src.model_factory`, and the builders stay in the
scripted harness, where every zero-token test takes its models from.
"""

import inspect

import pytest

from src import model_factory
from src.agents import (
    QA_LEGAL_MODEL_ID,
    QA_LEGAL_REASONING_EFFORT,
    SCOUT_MODEL_ID,
    SCOUT_REASONING_EFFORT,
    WRITER_MODEL_ID,
    WRITER_REASONING_EFFORT,
)
from src.model_factory import ModelBuilder, build_model
from tests.support.scripted import ScriptedModel, scripted_model_builder, scripted_model_builder_by_effort


def test_model_builder_is_exported_by_the_model_factory() -> None:
    """The seam's type lives beside the one real builder, not beside a composition root."""
    assert "ModelBuilder" in model_factory.__all__


def test_model_builder_takes_the_model_id_and_a_keyword_only_effort() -> None:
    """D24: the effort travels with the construction request, as a keyword, defaulting to none."""
    parameters = inspect.signature(ModelBuilder.__call__).parameters

    assert list(parameters) == ["self", "model_id", "reasoning_effort"]
    assert parameters["reasoning_effort"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["reasoning_effort"].default is None


def test_build_model_fits_the_model_builder_call_shape() -> None:
    """The production builder is callable exactly as the seam calls it: ``(model_id, *, reasoning_effort=…)``."""
    parameters = inspect.signature(build_model).parameters

    assert next(iter(parameters)) == "model_id"
    assert parameters["reasoning_effort"].kind is inspect.Parameter.KEYWORD_ONLY
    assert all(p.default is not inspect.Parameter.empty for name, p in parameters.items() if name != "model_id")


def test_scripted_model_builder_hands_out_one_model_per_model_id() -> None:
    """Approach 1's form: the fast model for the Scout's ID, the strong one for ``gpt-5.4``, whatever the effort."""
    fast, strong = ScriptedModel([]), ScriptedModel([])
    builder: ModelBuilder = scripted_model_builder(fast, strong)

    assert builder(SCOUT_MODEL_ID, reasoning_effort=SCOUT_REASONING_EFFORT) is fast
    assert builder(WRITER_MODEL_ID, reasoning_effort=WRITER_REASONING_EFFORT) is strong
    assert builder(QA_LEGAL_MODEL_ID, reasoning_effort=QA_LEGAL_REASONING_EFFORT) is strong


def test_scripted_model_builder_by_effort_returns_the_model_scripted_for_each_key() -> None:
    """Keyed on ``(model_id, reasoning_effort)``, so the Writer and QA-Legal can each get their own script."""
    scout, writer, qa_legal = ScriptedModel([]), ScriptedModel([]), ScriptedModel([])
    builder: ModelBuilder = scripted_model_builder_by_effort(
        {
            (SCOUT_MODEL_ID, SCOUT_REASONING_EFFORT): scout,
            (WRITER_MODEL_ID, WRITER_REASONING_EFFORT): writer,
            (QA_LEGAL_MODEL_ID, QA_LEGAL_REASONING_EFFORT): qa_legal,
        }
    )

    assert builder(SCOUT_MODEL_ID) is scout
    assert builder(WRITER_MODEL_ID, reasoning_effort=WRITER_REASONING_EFFORT) is writer
    assert builder(QA_LEGAL_MODEL_ID, reasoning_effort=QA_LEGAL_REASONING_EFFORT) is qa_legal


def test_scripted_model_builder_by_effort_rejects_an_unscripted_key() -> None:
    """A role the test did not script fails loudly, naming the key, instead of reusing another role's model."""
    builder = scripted_model_builder_by_effort({(SCOUT_MODEL_ID, None): ScriptedModel([])})

    with pytest.raises(AssertionError, match=r"\('gpt-5\.4', 'high'\)"):
        builder(WRITER_MODEL_ID, reasoning_effort="high")
