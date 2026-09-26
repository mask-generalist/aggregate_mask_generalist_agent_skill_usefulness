"""
Client subpackage.

`LLMClient` (the abstract base) is always importable — it has no optional
dependencies. The concrete implementations are imported lazily so that
`import agent_inspect.clients` succeeds even when the optional extras are
not installed:

  * `AzureOpenAIClient` requires the `azure-openai` extra (openai, backoff).
  * `LiteLLMClient` requires the `litellm` extra (litellm, openai, backoff).

If you reference one of those names without the corresponding dependencies
installed, you will get an ImportError pointing you at the right pip extra.
"""

from typing import TYPE_CHECKING

from .llm_client import LLMClient as LLMClient

# Map of lazily-exposed names -> (submodule, attribute, install hint).
# Add new clients here; nothing else needs to change.
_LAZY_ATTRS = {
    "AzureOpenAIClient": (
        ".azure_openai_client",
        "AzureOpenAIClient",
        'pip install "agent_inspect[azure-openai]"',
    ),
    "LiteLLMClient": (
        ".litellm_client",
        "LiteLLMClient",
        'pip install "agent_inspect[litellm]"',
    ),
}

__all__ = ["LLMClient", *_LAZY_ATTRS.keys()]


def __getattr__(name: str):
    """PEP 562 hook — resolves lazy attributes on first access."""
    try:
        module_path, attr, hint = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    from importlib import import_module

    try:
        module = import_module(module_path, package=__name__)
    except ImportError as exc:
        raise ImportError(
            f"{name} requires optional dependencies that are not installed. "
            f"Install them with: {hint}"
        ) from exc

    value = getattr(module, attr)
    # Cache on the package so subsequent lookups skip __getattr__.
    globals()[name] = value
    return value


def __dir__():
    return sorted(__all__)


# Help static type-checkers (pyright, mypy) see the names without forcing
# the imports at runtime.
if TYPE_CHECKING:
    from .azure_openai_client import AzureOpenAIClient as AzureOpenAIClient
    from .litellm_client import LiteLLMClient as LiteLLMClient
