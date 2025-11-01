import os
from openai import OpenAI

def test_agent_smoke():
    key = os.getenv("OPENAI_API_KEY")
    assert key and len(key) > 20
    client = OpenAI()
    first = next(iter(client.models.list().data), None)
    assert first is not None
