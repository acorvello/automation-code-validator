import requests

r = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "qwen3.5:9b",
        "prompt": 'Responda apenas JSON valido: {"needs_fix": true, "reason": "test"}',
        "format": "json",
        "stream": False,
    },
    timeout=120,
)
print(r.status_code)
print(r.json().get("response", "")[:300])
