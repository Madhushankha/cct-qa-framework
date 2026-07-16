"""Descriptor validation (load-time) + cross-reference integrity."""
from __future__ import annotations

from pathlib import Path

from core.descriptors import Feed, Product, Env, SEEDSPEC_REQUIRED
from core.registry import (
    REGISTRY_DIR, load_feed, load_product, load_env,
    list_feeds, list_products, list_envs, RegistryError,
)

_OTP_STRATEGIES = {"mailinator", "fixed"}


class DescriptorError(Exception):
    pass


def validate_feed(f: Feed) -> None:
    if not f.id or not f.gap_doc:
        raise DescriptorError(f"feed '{f.id}': 'id' and 'gap_doc' are required")
    for field in SEEDSPEC_REQUIRED:
        if field not in f.columns:
            raise DescriptorError(f"feed '{f.id}': columns missing SeedSpec field '{field}'")
    if not f.persona.get("default"):
        raise DescriptorError(f"feed '{f.id}': persona.default is required")
    if not f.judge.get("verdict_enum"):
        raise DescriptorError(f"feed '{f.id}': judge.verdict_enum is required")
    if not f.checkpoints.get("auditor"):
        raise DescriptorError(f"feed '{f.id}': checkpoints.auditor is required")


def validate_product(p: Product) -> None:
    if not p.id:
        raise DescriptorError("product: 'id' is required")
    if not isinstance(p.defaults.get("envs"), list) or not isinstance(p.defaults.get("feeds"), list):
        raise DescriptorError(f"product '{p.id}': defaults.envs and defaults.feeds must be lists")


def validate_env(e: Env) -> None:
    if not e.id:
        raise DescriptorError("env: 'id' is required")
    strategy = e.otp.get("strategy")
    if strategy not in _OTP_STRATEGIES:
        raise DescriptorError(
            f"env '{e.id}': otp.strategy '{strategy}' invalid (must be one of {sorted(_OTP_STRATEGIES)})")
    if strategy == "mailinator" and not e.otp.get("token_secret"):
        raise DescriptorError(f"env '{e.id}': mailinator otp requires 'token_secret' (a secret NAME)")
    if strategy == "fixed" and not e.otp.get("code"):
        raise DescriptorError(f"env '{e.id}': fixed otp requires 'code'")
    for key in ("base_url", "endpoint_path", "region"):
        if not e.chatbot.get(key):
            raise DescriptorError(f"env '{e.id}': chatbot.{key} is required")


def validate_all() -> list[str]:
    errors: list[str] = []
    feeds = list_feeds()
    envs = list_envs()
    for fid in feeds:
        try:
            f = load_feed(fid)
            validate_feed(f)
            parent = (REGISTRY_DIR.parent.parent / Path(f.gap_doc)).parent
            if not parent.exists():
                errors.append(f"feed '{fid}': gap_doc directory does not exist: {parent}")
        except (DescriptorError, RegistryError) as ex:
            errors.append(str(ex))
    for eid in envs:
        try:
            validate_env(load_env(eid))
        except (DescriptorError, RegistryError) as ex:
            errors.append(str(ex))
    for pid in list_products():
        try:
            p = load_product(pid)
            validate_product(p)
            for ref in p.defaults.get("feeds", []):
                if ref not in feeds:
                    errors.append(f"product '{pid}': defaults.feeds references unknown feed '{ref}'")
            for ref in p.defaults.get("envs", []):
                if ref not in envs:
                    errors.append(f"product '{pid}': defaults.envs references unknown env '{ref}'")
        except (DescriptorError, RegistryError) as ex:
            errors.append(str(ex))
    return errors
