from __future__ import annotations

import json

import pytest

from codex_hl.live.fragment_sandbox import (
    FragmentSandboxError,
    execute_fragment_post_helpers,
    execute_fragment_pre_helpers,
    read_fragment_compat_events,
    read_fragment_events,
    read_registered_fragment,
    register_fragment_binding,
    validate_fragment_execution_binding,
)
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import normalize_turn_plan


def plan_payload(**step_overrides) -> dict:
    step = {
        "step_id": "s001",
        "tool": "unit_action",
        "args": {"unit_id": 65536, "action": "skip"},
        "allowed_mutation_level": "L2",
        "fragment_allowed": True,
        "postconditions": [],
    }
    step.update(step_overrides)
    return {
        "episode_id": "ep_fragment",
        "plan_id": "plan_t0001_v01",
        "turn": 1,
        "branch_id": "b000",
        "context_hash": "sha256:ctx",
        "steps": [step],
    }


def make_store(tmp_path, *, arm: bool = False, plan: dict | None = None) -> LivePlanStore:
    store = LivePlanStore.for_episode_root(tmp_path / "ep_fragment", "ep_fragment")
    store.start_episode(
        save_name="test 1",
        target_turns=3,
        mode="live_strict",
        runner="live-json-plan",
    )
    store.record_turn_context(
        turn=1,
        branch_id="b000",
        context_hash="sha256:ctx",
        payload={
            "overview": {"turn": 1},
            "units": [{"unit_id": 65536, "x": 1, "y": 1}],
            "cities": [{"city_id": 99, "name": "Capital"}],
        },
    )
    store.submit_plan(normalize_turn_plan(plan or plan_payload()))
    if arm:
        store.arm_step("plan_t0001_v01", "s001")
    return store


def fragment_source(**overrides) -> str:
    args = {"unit_id": 65536, "action": "skip"}
    args.update(overrides)
    kwargs = ", ".join(f"{key}={value!r}" for key, value in args.items())
    return f"def run(live):\n    return live.unit_action({kwargs})\n"


def helper_fragment_source(
    *,
    precondition: str = "unit_exists",
    precondition_arg: str = "unit_id",
    precondition_value: int = 65536,
    postcondition: bool = False,
) -> str:
    post = ""
    if postcondition:
        post = (
            "\n"
            "    live.assert_postcondition("
            "\"unit_position_changed_or_blocked\", unit_id=65536)"
        )
    return (
        "def run(live):\n"
        "    ctx = live.read_context()\n"
        f"    live.assert_precondition(\"{precondition}\", "
        f"{precondition_arg}={precondition_value})\n"
        "    result = live.unit_action(unit_id=65536, action=\"skip\")"
        f"{post}\n"
        "    return {\"result\": result, \"ctx\": ctx}\n"
    )


def test_register_fragment_requires_feature_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", raising=False)
    store = make_store(tmp_path)

    with pytest.raises(FragmentSandboxError, match="disabled"):
        register_fragment_binding(
            plan_store=store,
            source=fragment_source(),
            episode_id="ep_fragment",
            plan_id="plan_t0001_v01",
            step_id="s001",
            context_hash="sha256:ctx",
        )


def test_register_fragment_requires_step_opt_in(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    plan = plan_payload(fragment_allowed=False)
    store = make_store(tmp_path, plan=plan)

    with pytest.raises(FragmentSandboxError, match="does not allow"):
        register_fragment_binding(
            plan_store=store,
            source=fragment_source(),
            episode_id="ep_fragment",
            plan_id="plan_t0001_v01",
            step_id="s001",
            context_hash="sha256:ctx",
        )


def test_register_fragment_requires_args_to_match_step(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path)

    with pytest.raises(FragmentSandboxError, match="args"):
        register_fragment_binding(
            plan_store=store,
            source=fragment_source(action="fortify"),
            episode_id="ep_fragment",
            plan_id="plan_t0001_v01",
            step_id="s001",
            context_hash="sha256:ctx",
        )


def test_registered_fragment_must_be_armed_before_execution(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path, arm=False)
    binding = register_fragment_binding(
        plan_store=store,
        source=fragment_source(),
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )

    with pytest.raises(FragmentSandboxError, match="ARMED"):
        validate_fragment_execution_binding(
            plan_store=store,
            fragment_id=binding["fragment_id"],
            episode_id="ep_fragment",
            plan_id="plan_t0001_v01",
            step_id="s001",
            context_hash="sha256:ctx",
        )


def test_registered_fragment_execution_binding_records_and_validates(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path, arm=True)
    binding = register_fragment_binding(
        plan_store=store,
        source=fragment_source(),
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )

    validated = validate_fragment_execution_binding(
        plan_store=store,
        fragment_id=binding["fragment_id"],
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )

    assert validated["fragment_id"] == binding["fragment_id"]
    events = read_fragment_events(
        episode_root=store.episode_root, episode_id="ep_fragment"
    )
    assert events[-1]["event_type"] == "FRAGMENT_REGISTERED"
    assert events[-1]["payload"]["source_sha256"].startswith("sha256:")
    assert events[-1]["source"] == "fragment"
    compat_events = read_fragment_compat_events(
        episode_root=store.episode_root, episode_id="ep_fragment"
    )
    assert compat_events[-1]["event_type"] == "FRAGMENT_REGISTERED"
    assert compat_events[-1]["ledger_event_ids"] == binding["ledger_event_ids"]


def test_read_registered_fragment_prefers_ledger_over_compat_log(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path, arm=True)
    binding = register_fragment_binding(
        plan_store=store,
        source=fragment_source(),
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )
    compat_path = store.episode_root / "raw" / "live_fragments.jsonl"
    fake = {
        "event_type": "FRAGMENT_REGISTERED",
        "payload": {
            **binding,
            "args": {"unit_id": 65536, "action": "fortify"},
        },
    }
    with compat_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fake) + "\n")

    registered = read_registered_fragment(
        episode_root=store.episode_root,
        episode_id="ep_fragment",
        fragment_id=binding["fragment_id"],
    )

    assert registered is not None
    assert registered["args"] == {"unit_id": 65536, "action": "skip"}


def test_read_registered_fragment_falls_back_to_compat_log(tmp_path) -> None:
    episode_root = tmp_path / "ep_fragment"
    compat_path = episode_root / "raw" / "live_fragments.jsonl"
    compat_path.parent.mkdir(parents=True)
    compat_path.write_text(
        json.dumps(
            {
                "event_type": "FRAGMENT_REGISTERED",
                "payload": {
                    "fragment_id": "frag_compat",
                    "episode_id": "ep_fragment",
                    "plan_id": "plan_t0001_v01",
                    "step_id": "s001",
                    "context_hash": "sha256:ctx",
                    "tool_name": "unit_action",
                    "args": {"unit_id": 65536, "action": "skip"},
                    "source_sha256": "sha256:source",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registered = read_registered_fragment(
        episode_root=episode_root,
        episode_id="ep_fragment",
        fragment_id="frag_compat",
    )

    assert registered is not None
    assert registered["source_sha256"] == "sha256:source"


def test_fragment_helpers_read_context_and_precondition_trace(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    plan = plan_payload(
        postconditions=[{"type": "unit_position_changed_or_blocked", "unit_id": 65536}]
    )
    store = make_store(tmp_path, arm=True, plan=plan)
    binding = register_fragment_binding(
        plan_store=store,
        source=helper_fragment_source(postcondition=True),
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )

    pre_trace = execute_fragment_pre_helpers(plan_store=store, binding=binding)
    post_trace = execute_fragment_post_helpers(plan_store=store, binding=binding)

    assert pre_trace[0]["name"] == "read_context"
    assert pre_trace[0]["summary"]["unit_count"] == 1
    assert pre_trace[1]["name"] == "assert_precondition"
    assert pre_trace[1]["status"] == "PASS"
    assert post_trace == [
        {
            "name": "assert_postcondition",
            "status": "DEFERRED_TO_VERIFIER",
            "condition": {
                "type": "unit_position_changed_or_blocked",
                "unit_id": 65536,
            },
        }
    ]


def test_fragment_precondition_failure_rejects_before_action(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path, arm=True)
    binding = register_fragment_binding(
        plan_store=store,
        source=helper_fragment_source(
            precondition="city_exists",
            precondition_arg="city_id",
            precondition_value=404,
        ),
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )

    with pytest.raises(FragmentSandboxError, match="city_exists"):
        execute_fragment_pre_helpers(plan_store=store, binding=binding)


def test_fragment_unknown_precondition_rejects_before_action(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path, arm=True)
    binding = register_fragment_binding(
        plan_store=store,
        source=helper_fragment_source(precondition="gold_available"),
        episode_id="ep_fragment",
        plan_id="plan_t0001_v01",
        step_id="s001",
        context_hash="sha256:ctx",
    )

    with pytest.raises(FragmentSandboxError, match="unsupported"):
        execute_fragment_pre_helpers(plan_store=store, binding=binding)


def test_fragment_postconditions_must_match_planned_step(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")
    store = make_store(tmp_path, arm=True)

    with pytest.raises(FragmentSandboxError, match="postconditions"):
        register_fragment_binding(
            plan_store=store,
            source=helper_fragment_source(postcondition=True),
            episode_id="ep_fragment",
            plan_id="plan_t0001_v01",
            step_id="s001",
            context_hash="sha256:ctx",
        )
