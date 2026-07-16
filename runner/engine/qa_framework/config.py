"""ChatbotConfig — the Amazon Connect chat client's per-run settings.

Trimmed from the cct-qa-1 vendor: the framework always injects a ChatbotConfig
built from the Env descriptor (see runner.build.chat_config_from_env), so only the
ChatbotConfig dataclass and a minimal ``cfg`` fallback (an empty default config the
client uses when no config is passed) are kept. No YAML/env loading lives here."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChatbotConfig:
    base_url: str = "http://localhost:8000"
    api_key: str = ""
    endpoint_path: str = "/start-chat"
    region: str = "ca-central-1"
    init_payload: dict = field(default_factory=dict)
    timeout_seconds: int = 30
    response_timeout_seconds: int = 45


@dataclass
class _Cfg:
    """Minimal stand-in for the old global config singleton. The client falls back to
    ``cfg.chatbot`` only when constructed with config=None; the framework never relies
    on that path (it always injects a ChatbotConfig)."""
    chatbot: ChatbotConfig = field(default_factory=ChatbotConfig)


cfg = _Cfg()
