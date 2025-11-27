from openai import OpenAI

from backend.utils.openai_key import load_openai_api_key

def test_agent_smoke():
    key = load_openai_api_key()
    assert len(key) > 20
    client = OpenAI(api_key=key)
    first = next(iter(client.models.list().data), None)
    assert first is not None
