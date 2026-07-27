from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples._lib.run_mcp import (
    ROOT,
    extract_agent_response,
    pick_python,
    prepare_city,
    select_block_id,
)


def test_pick_python_uses_existing_cross_platform_interpreter() -> None:
    python = Path(pick_python())

    assert python.exists()
    assert "Scripts/python.exe" not in str(python).replace("\\", "/")


def test_prepare_city_yuzhno_creates_ready_symlink_prep() -> None:
    prep = prepare_city("yuzhno-sakhalinsk")

    assert prep.ready is True
    assert prep.prep_dir.is_absolute()
    blocks_link = prep.prep_dir / "blocks_with_services.gpkg"
    assert blocks_link.exists()
    assert blocks_link.resolve() == (ROOT / "examples/yuzhno-sakhalinsk/data/blocks.gpkg").resolve()
    assert (prep.prep_dir / "acc_mx.pickle").exists()
    assert (prep.prep_dir / "service_type.json").exists()
    assert (prep.prep_dir / "services").exists()
    assert prep.block_count == 903
    assert prep.has_capacity is True
    assert prep.has_population is True
    assert prep.has_land_use is True


def test_prepare_city_saint_petersburg_uses_prepared_blocks_with_services() -> None:
    prep = prepare_city("saint_petersburg")

    assert prep.ready is True
    assert prep.reason is None
    assert (prep.prep_dir / "blocks_with_services.gpkg").resolve() == (
        ROOT / "examples/saint_petersburg/data/blocks_with_services.gpkg"
    ).resolve()
    assert (prep.prep_dir / "acc_mx.pickle").exists()
    assert prep.block_count == 9368
    assert prep.has_capacity is True
    assert prep.has_population is True
    assert prep.has_land_use is True


def test_select_block_id_uses_top_populated_residential_candidate() -> None:
    prep = prepare_city("yuzhno-sakhalinsk")

    selection = select_block_id(prep)

    assert selection["method"] == "auto_top_population"
    assert isinstance(selection["block_id"], int)
    assert 0 <= selection["block_id"] <= 902
    assert selection["population"] > 0


def test_select_block_id_honors_explicit_valid_id() -> None:
    prep = prepare_city("yuzhno-sakhalinsk")

    selection = select_block_id(prep, explicit_block_id=42)

    assert selection == {"block_id": 42, "method": "explicit", "population": pytest.approx(selection["population"])}


def test_extract_agent_response_prefers_content_text_json() -> None:
    sample = json.loads((ROOT / "examples/saint_petersburg/outputs/spb_city_mean_via_mcp.json").read_text(encoding="utf-8"))

    payload = extract_agent_response(sample["result"])

    assert payload["question"] == "Какая средняя доступность Санкт-Петербурга?"
    assert payload["run_id"] == "20260623-170049-6cc7f0"
    assert payload["confidence"] == 0.45


def test_extract_agent_response_accepts_structured_content() -> None:
    payload = extract_agent_response({"structuredContent": {"question": "q", "confidence": 0.1}})

    assert payload == {"question": "q", "confidence": 0.1}
