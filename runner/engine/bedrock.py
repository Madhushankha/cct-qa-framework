"""Bedrock Converse plumbing — extracted from cct-qa-1/fd-int-flow/run_fd_flow.py.

Provides the customer-simulator / judge LLM driver: bedrock_client(), converse() (with
retry/backoff), tool_input(), and the CUSTOMER_TOOL (customer_turn) tool schema. The model id
is configurable (default the Sonnet id from the CRT config).

boto3/botocore imports are LAZY (inside functions) so this module imports offline with only the
base deps — the live extra is needed only to actually call Bedrock.

A process-wide concurrency limiter can be installed via set_concurrency(n): the orchestrator uses
it as the 'shared Bedrock semaphore' so many concurrent sessions don't overrun the model TPS."""
from __future__ import annotations

import os
import threading

# Default driver model + region (from cct-qa-1 config_crt.json). Configurable per call.
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_REGION = "ca-central-1"

# ── LLM customer driver tool schema (Bedrock Converse, tool-forced) ──────────
CUSTOMER_TOOL = {
    "toolSpec": {
        "name": "customer_turn",
        "description": "Send the next message as the customer, and flag when the assistant has delivered a FINAL outcome.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The exact text to send to the assistant this turn (short, natural, one customer message)."},
                "conversation_complete": {"type": "boolean", "description": "True ONLY when the assistant has given a final outcome (a decision + amount, OR a clear not-eligible / handed-to-agent result)."},
                "private_note": {"type": "string", "description": "One-line internal note on why you said this / what the assistant just did. Not sent to the bot."},
            },
            "required": ["message", "conversation_complete"],
        }},
    }
}


# ── shared Bedrock concurrency limiter ───────────────────────────────────────
_SEM: threading.Semaphore | None = None


def set_concurrency(n: int | None) -> None:
    """Install (or clear, with None) a process-wide semaphore that converse() respects.
    The orchestrator calls this once so all sessions share one Bedrock TPS budget."""
    global _SEM
    _SEM = threading.Semaphore(n) if n and n > 0 else None


def bedrock_client(region: str = DEFAULT_REGION, profile: str | None = None):
    """Build a bedrock-runtime client with adaptive retries + generous timeouts so transient
    connection blips (common under load / high concurrency) are retried inside boto3."""
    import boto3  # lazy
    from botocore.config import Config

    cfg = Config(retries={"max_attempts": 8, "mode": "adaptive"},
                 connect_timeout=15, read_timeout=90, max_pool_connections=4)
    prof = profile or os.getenv("AWS_PROFILE")
    if prof:
        return boto3.Session(profile_name=prof, region_name=region).client("bedrock-runtime", config=cfg)
    return boto3.client("bedrock-runtime", region_name=region, config=cfg)


def converse(client, system, messages, tool, model_id: str = DEFAULT_MODEL_ID):
    """One tool-forced Converse call with explicit backoff on transient boto errors, honouring the
    shared concurrency semaphore if one is installed."""
    import time as _t
    from botocore.exceptions import (EndpointConnectionError, ConnectionClosedError, ConnectTimeoutError,
                                     ReadTimeoutError, TokenRetrievalError)
    # TokenRetrievalError too: with many concurrent processes a transient SSO-cache read race can throw
    # even when the token is valid — a short backoff + retry usually succeeds (genuine expiry still fails out).
    transient = (EndpointConnectionError, ConnectionClosedError, ConnectTimeoutError, ReadTimeoutError, TokenRetrievalError)
    sem = _SEM
    if sem is not None:
        sem.acquire()
    try:
        last = None
        for attempt in range(6):                       # extra explicit backoff on top of boto's retries
            try:
                return client.converse(
                    modelId=model_id,
                    system=[{"text": system}],
                    messages=messages,
                    toolConfig={"tools": [tool], "toolChoice": {"tool": {"name": tool["toolSpec"]["name"]}}},
                    inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
                )
            except transient as e:
                last = e
                _t.sleep(min(2 ** attempt, 20))        # 1,2,4,8,16,20s
        raise last
    finally:
        if sem is not None:
            sem.release()


def tool_input(resp, name):
    """Pull the (input, toolUseId) for the named tool out of a Converse response, or (None, None)."""
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block and block["toolUse"]["name"] == name:
            return block["toolUse"]["input"], block["toolUse"]["toolUseId"]
    return None, None
