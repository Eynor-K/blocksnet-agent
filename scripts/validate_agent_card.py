#!/usr/bin/env python
"""Проверка Agent Card против исполняемой схемы CodeSynapse (A2A 1.0).

Тот же контракт, что и в ``tests/test_codesynapse_contract.py``, но против
**поднятого** сервиса — так проверяют перед регистрацией в чужом тенанте.

    # против локально поднятого `python -m blocksnet_agent`
    python scripts/validate_agent_card.py --url http://127.0.0.1:8080

    # против уже развёрнутого сервиса
    python scripts/validate_agent_card.py --url https://blocksnet.example.org

    # без сети: карточка собирается in-process (как в smoke_a2a_agent.py)
    python scripts/validate_agent_card.py

Схема берётся из ``A2A_CONTRACTS_DIR`` либо из snapshot
``docs/dev/codesynapse/docs/contracts/a2a``. Схему не копируем к себе — она
принадлежит принимающей стороне (решение Д4 плана
``docs/dev/plans/codesynapse/``).

Exit code: 0 — карточка валидна; 1 — есть расхождения; 2 — не удалось получить
карточку или схему.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CONTRACTS_DIR = PROJECT_ROOT / "docs" / "dev" / "codesynapse" / "docs" / "contracts" / "a2a"
SCHEMA_FILE = "synapse-a2a-1.0.schema.json"
CARD_ROUTE = "/.well-known/agent-card.json"

LEGACY_03_CARD_FIELDS = (
    "protocolVersion",
    "url",
    "preferredTransport",
    "additionalInterfaces",
    "supportsAuthenticatedExtendedCard",
)


def _contracts_dir() -> Path:
    configured = os.getenv("A2A_CONTRACTS_DIR")
    return Path(configured) if configured else DEFAULT_CONTRACTS_DIR


def _load_schema() -> Dict[str, Any]:
    path = _contracts_dir() / SCHEMA_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"схема не найдена: {path}. Положите snapshot CodeSynapse в "
            "docs/dev/codesynapse или задайте A2A_CONTRACTS_DIR."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch_card(url: str | None) -> Dict[str, Any]:
    if url:
        import urllib.request

        endpoint = url.rstrip("/") + CARD_ROUTE
        with urllib.request.urlopen(endpoint, timeout=30) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    from starlette.testclient import TestClient

    from blocksnet_agent.a2a.server import build_app

    response = TestClient(build_app()).get(CARD_ROUTE)
    if response.status_code != 200:
        raise RuntimeError(f"{CARD_ROUTE} вернул {response.status_code}: {response.text}")
    return response.json()


def validate(card: Dict[str, Any], schema: Dict[str, Any]) -> list[str]:
    """Вернуть список человекочитаемых расхождений (пустой — карточка валидна)."""
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/agentCard"},
        format_checker=FormatChecker(),
    )
    problems = [
        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(card), key=lambda e: list(e.path))
    ]

    legacy = [field for field in LEGACY_03_CARD_FIELDS if field in card]
    if legacy:
        problems.append(
            f"<root>: legacy-поля профиля 0.3 рядом с supportedInterfaces: {legacy}"
        )

    versions = {
        interface.get("protocolVersion")
        for interface in card.get("supportedInterfaces") or []
        if isinstance(interface, dict)
    }
    if versions and versions != {"1.0"}:
        problems.append(
            f"supportedInterfaces/protocolVersion: ожидается строго '1.0', получено {sorted(versions)}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=None,
        help="базовый URL сервиса; без него карточка собирается in-process",
    )
    parser.add_argument("--print-card", action="store_true", help="вывести карточку целиком")
    args = parser.parse_args(argv)

    try:
        schema = _load_schema()
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    try:
        card = _fetch_card(args.url)
    except Exception as exc:  # noqa: BLE001 — источник карточки внешний
        print(f"FAIL: не удалось получить {CARD_ROUTE}: {exc}", file=sys.stderr)
        return 2

    if args.print_card:
        print(json.dumps(card, ensure_ascii=False, indent=2))

    source = args.url or "in-process"
    problems = validate(card, schema)
    if problems:
        print(f"FAIL: Agent Card ({source}) — {len(problems)} расхождений:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    skills = ", ".join(skill.get("id", "?") for skill in card.get("skills", []))
    print(
        f"OK: Agent Card ({source}) валидна по A2A 1.0 (schema: {SCHEMA_FILE}).\n"
        f"    name={card.get('name')} version={card.get('version')} skills=[{skills}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
