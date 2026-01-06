from llm import provider_registry
from llm.providers.openai_provider import OpenAIProvider


def test_default_provider_is_openai(monkeypatch):
    provider_registry.reset_provider_for_tests()
    provider = provider_registry.get_provider()
    assert isinstance(provider, OpenAIProvider)
    assert provider.supports_json_schema() is True