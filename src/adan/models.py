from langchain_openai import ChatOpenAI

from adan.config import Settings


class OpenRouterModels:
    """Provider transport only. No benchmark labels, answers or model-selection experiments."""

    def __init__(self, settings: Settings):
        if not settings.openrouter_api_key.get_secret_value():
            raise ValueError("Set OPENROUTER_API_KEY in the environment before starting")
        self.settings = settings
        self.clients = {}

    async def call(self, purpose, messages, *, tools=None, schema=None, fallback=False):
        model = self.settings.text_model
        if purpose == "coordinator":
            model = self.settings.router_fallback_model if fallback else self.settings.router_model
        if model not in self.clients:
            self.clients[model] = ChatOpenAI(
                model=model,
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
                temperature=0,
                timeout=self.settings.model_timeout_seconds,
                max_retries=0,
                max_tokens=4096,
                extra_body={"reasoning": {"enabled": False}},
            )
        client = self.clients[model]
        if tools:
            client = client.bind_tools(tools)
        if schema:
            client = client.bind(
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": False,
                        "schema": schema.model_json_schema(),
                    },
                }
            )
        return await client.ainvoke(messages)
