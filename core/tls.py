"""One TLS trust configuration for every outbound leg the framework makes.

`ssl.create_default_context()` trusts whatever the interpreter was built to trust. On a python.org
macOS framework build that is NOTHING until `Install Certificates.command` has been run, so ordinary
AWS certificates fail with CERTIFICATE_VERIFY_FAILED — the MSK brokers, the Amazon Connect
start-chat endpoint, the chat WebSocket and the Mailinator API all died that way on a clean install,
while boto3 kept working because botocore vendors its own CA bundle.

Trusting certifi's bundle fixes all of them and keeps verification ON. `QA_INSECURE_TLS=1` remains
the escape hatch for a TLS-inspecting middlebox; it disables verification, so it is a workaround and
never a fix.
"""
from __future__ import annotations

import os
import ssl


def insecure() -> bool:
    return os.getenv("QA_INSECURE_TLS", "").lower() in ("1", "true", "yes")


def ca_bundle() -> str | None:
    """Path to certifi's CA bundle, or None when certifi is not installed."""
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


def context() -> ssl.SSLContext:
    """Verifying SSL context for urllib/socket callers (unverified when QA_INSECURE_TLS=1)."""
    if insecure():
        return ssl._create_unverified_context()
    bundle = ca_bundle()
    return ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()


def ws_sslopt() -> dict:
    """Equivalent trust settings for websocket-client's `sslopt` argument."""
    if insecure():
        return {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
    bundle = ca_bundle()
    return {"ca_certs": bundle} if bundle else {}
