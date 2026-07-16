"""Secret resolution by name. P0 impl reads environment variables only (offline).
Future envs can supply an AWS Secrets Manager resolver behind the same interface."""
from __future__ import annotations

import os
from typing import Protocol


class SecretError(Exception):
    pass


class SecretResolver(Protocol):
    def resolve(self, name: str) -> str: ...


class EnvSecretResolver:
    def resolve(self, name: str) -> str:
        val = os.environ.get(name)
        if not val:
            raise SecretError(f"secret '{name}' is not set (expected environment variable '{name}')")
        return val


_default = EnvSecretResolver()


def resolve_secret(name: str) -> str:
    return _default.resolve(name)
