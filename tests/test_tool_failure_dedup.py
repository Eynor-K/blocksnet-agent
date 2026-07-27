from __future__ import annotations

from langchain_core.tools import tool

from blocksnet_agent.tools import _memoize_tools


def test_repeated_identical_failed_tool_call_is_action_blocked():
    calls = {"count": 0}

    @tool
    def compute_bad(service_type: str) -> str:
        """Synthetic failing compute tool."""
        calls["count"] += 1
        return f"Ошибка: unknown service {service_type}"

    wrapped = _memoize_tools([compute_bad])[0]

    first = wrapped.invoke({"service_type": "unknown"})
    second = wrapped.invoke({"service_type": "unknown"})

    assert first.startswith("Ошибка:")
    assert second.startswith("REPEATED_FAILED_CALL")
    assert "unknown service unknown" in second
    assert calls["count"] == 1


def test_corrected_arguments_are_not_blocked_by_failed_call_cache():
    calls = []

    @tool
    def compute_service(service_type: str) -> str:
        """Synthetic compute tool with one invalid service."""
        calls.append(service_type)
        if service_type == "bad":
            return "Ошибка: bad service"
        return f"ok {service_type}"

    wrapped = _memoize_tools([compute_service])[0]

    assert wrapped.invoke({"service_type": "bad"}).startswith("Ошибка:")
    assert wrapped.invoke({"service_type": "good"}) == "ok good"

    assert calls == ["bad", "good"]


def test_successful_compute_memoization_still_works():
    calls = {"count": 0}

    @tool
    def compute_ok(service_type: str) -> str:
        """Synthetic successful compute tool."""
        calls["count"] += 1
        return f"ok {service_type}"

    wrapped = _memoize_tools([compute_ok])[0]

    assert wrapped.invoke({"service_type": "school"}) == "ok school"
    assert wrapped.invoke({"service_type": "school"}) == "ok school"
    assert calls["count"] == 1
