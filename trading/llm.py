import json

import requests
from django.conf import settings


class NineRouterClient:
    def __init__(self):
        config = settings.NINEROUTER
        self.base_url = config["base_url"]
        self.api_key = config["api_key"]
        self.model = config["model"]

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def models(self):
        response = requests.get(f"{self.base_url}/models", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json().get("data", [])

    def explain(self, payload):
        if not self.model:
            raise ValueError("NINEROUTER_MODEL has not been selected")
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            timeout=60,
            json={
                "model": self.model,
                "stream": False,
                "temperature": 0.1,
                "max_tokens": 500,
                "messages": [
                    {
                        "role": "system",
                        "content": "Explain the supplied quant output in concise Indonesian. Never change numeric levels, issue a trade, or override a risk veto.",
                    },
                    {"role": "user", "content": str(payload)},
                ],
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            payload, _ = json.JSONDecoder().raw_decode(response.text)
        return payload["choices"][0]["message"]["content"]
