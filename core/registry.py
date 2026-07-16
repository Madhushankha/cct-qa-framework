"""Descriptor discovery + loading. Reads YAML from core/registry/ into dataclasses."""
from __future__ import annotations

from pathlib import Path

import yaml

from core.descriptors import Feed, Product, Env, RunContext

REGISTRY_DIR = Path(__file__).resolve().parent / "registry"


class RegistryError(Exception):
    pass


def _load_yaml(kind: str, id: str) -> dict:
    path = REGISTRY_DIR / kind / f"{id}.yaml"
    if not path.exists():
        raise RegistryError(f"{kind[:-1]} '{id}' not found (expected {path})")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegistryError(f"{path} did not parse to a mapping")
    if data.get("id") != id:
        raise RegistryError(f"{path}: top-level id '{data.get('id')}' != filename '{id}'")
    return data


def _ids(kind: str) -> list[str]:
    d = REGISTRY_DIR / kind
    return sorted(p.stem for p in d.glob("*.yaml")) if d.exists() else []


def load_feed(id: str) -> Feed:
    d = _load_yaml("feeds", id)
    return Feed(id=d["id"], label=d.get("label", id), gap_doc=d.get("gap_doc", ""),
                columns=d.get("columns", {}), persona=d.get("persona", {}),
                judge=d.get("judge", {}), checkpoints=d.get("checkpoints", {}),
                dataset=d.get("dataset", ""))


def load_product(id: str) -> Product:
    d = _load_yaml("products", id)
    return Product(id=d["id"], label=d.get("label", id),
                   transcript_dialect=d.get("transcript_dialect", id),
                   overrides=d.get("overrides", {}), defaults=d.get("defaults", {}))


def load_env(id: str) -> Env:
    d = _load_yaml("envs", id)
    return Env(id=d["id"], label=d.get("label", id), chatbot=d.get("chatbot", {}),
               aws=d.get("aws", {}), otp=d.get("otp", {}), seed_targets=d.get("seed_targets", {}))


def list_feeds() -> list[str]:
    return _ids("feeds")


def list_products() -> list[str]:
    return _ids("products")


def list_envs() -> list[str]:
    return _ids("envs")


def resolve(product: str, env: str, feed: str) -> RunContext:
    from core.validate import validate_feed, validate_product, validate_env

    p = load_product(product)
    e = load_env(env)
    f = load_feed(feed)
    validate_product(p)
    validate_env(e)
    validate_feed(f)

    allowed_feeds = p.defaults.get("feeds", [])
    allowed_envs = p.defaults.get("envs", [])
    if feed not in allowed_feeds:
        raise RegistryError(f"product '{product}' does not allow feed '{feed}' (allowed: {allowed_feeds})")
    if env not in allowed_envs:
        raise RegistryError(f"product '{product}' does not allow env '{env}' (allowed: {allowed_envs})")

    # layer the product's overrides onto the feed's persona/judge (product wins on key collision)
    overrides = p.overrides or {}
    persona = {**f.persona, **(overrides.get("persona") or {})}
    judge = {**f.judge, **(overrides.get("judge") or {})}
    return RunContext(product=p, env=e, feed=f, scenario_prefix=f"{product}.{env}.{feed}",
                      persona=persona, judge=judge)
