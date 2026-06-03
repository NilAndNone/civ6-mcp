import json
from pathlib import Path

from codex_hl.evidence.store import EpisodeStore
from codex_hl.live.human_demo_contract import (
    ASSUMPTIONS_AND_STOP_RULES,
    CHECKPOINTS,
    STAGES,
    STRATEGY_ESSENTIALS,
    evaluate_attempt_window,
    evaluate_episode_contract,
    render_markdown,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _context_event(episode_id: str, turn: int, *, cities: int = 1, era_score: int = 0) -> dict:
    return {
        "event_type": "TURN_CONTEXT_RECORDED",
        "payload": {
            "context": {
                "episode_id": episode_id,
                "turn": turn,
                "overview": {
                    "turn": turn,
                    "num_cities": cities,
                    "total_population": cities,
                    "science_yield": 2,
                    "culture_yield": 1,
                    "era_score": era_score,
                    "era_golden_threshold": 19,
                },
                "cities": [
                    {
                        "city_id": 1,
                        "name": "Xi'an",
                        "x": 62,
                        "y": 41,
                        "currently_building": "UNIT_SETTLER",
                        "production_turns_left": 5,
                    }
                ],
                "units": [{"unit_id": 1, "unit_index": 1, "unit_type": "UNIT_WARRIOR", "x": 62, "y": 42}],
                "threats": [],
                "resources": {"nearby": []},
                "research_civic": {},
            }
        },
    }


def _make_failed_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 50,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root / "raw" / "live_plan_events.jsonl",
        [
            _context_event(episode_id, 7, cities=1, era_score=0),
            _context_event(episode_id, 17, cities=1, era_score=0),
            _context_event(episode_id, 50, cities=1, era_score=0),
        ],
    )
    _write_jsonl(root / "raw" / "live_events.jsonl", [])


def _make_final_metric_success_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 50,
            }
        ),
        encoding="utf-8",
    )
    event = _context_event(episode_id, 50, cities=4, era_score=36)
    context = event["payload"]["context"]
    context["overview"].update(
        {
            "total_population": 20,
            "science_yield": 34.4,
            "culture_yield": 25.2,
        }
    )
    context["cities"] = [
        {"city_id": 1, "name": "Xi'an", "x": 62, "y": 41, "currently_building": "PROJECT_CAMPUS_RESEARCH_GRANTS"},
        {"city_id": 2, "name": "Yiyang", "x": 59, "y": 36, "currently_building": "NONE"},
        {"city_id": 3, "name": "Shanghai", "x": 65, "y": 37, "currently_building": "PROJECT_CAMPUS_RESEARCH_GRANTS"},
        {"city_id": 4, "name": "Nanjing", "x": 68, "y": 42, "currently_building": "NONE"},
    ]
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [event])
    _write_jsonl(root / "raw" / "live_events.jsonl", [])


def _make_wrong_chop_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 50,
            }
        ),
        encoding="utf-8",
    )
    event = _context_event(episode_id, 13, cities=1, era_score=7)
    context = event["payload"]["context"]
    context["cities"][0]["currently_building"] = "PROJECT_ENHANCE_DISTRICT_HOLY_SITE"
    context["cities"][0]["districts"] = ["DISTRICT_HOLY_SITE@63,39"]
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [event])
    _write_jsonl(
        root / "raw" / "live_events.jsonl",
        [
            {
                "event_type": "ACTION_FINISHED",
                "turn": 13,
                "seq": 1,
                "tool": "unit_action",
                "verifier_status": "PASS",
                "args": {"action": "remove_feature", "unit_index": 2},
                "payload": {"result": "OK:REMOVING_FEATURE|FEATURE_FOREST at 62,42"},
            }
        ],
    )


def _make_pre_window_religion_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 50,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root / "raw" / "live_plan_events.jsonl",
        [
            _context_event(episode_id, 17, cities=1, era_score=9),
            _context_event(episode_id, 20, cities=1, era_score=13),
        ],
    )
    _write_jsonl(
        root / "raw" / "live_events.jsonl",
        [
            {
                "event_type": "ACTION_FINISHED",
                "turn": 1,
                "seq": 1,
                "tool": "choose_pantheon",
                "verifier_status": "PASS",
                "args": {"belief_type": "BELIEF_RELIGIOUS_SETTLEMENTS"},
                "payload": {"result": "OK:PANTHEON|BELIEF_RELIGIOUS_SETTLEMENTS"},
            },
            {
                "event_type": "ACTION_FINISHED",
                "turn": 1,
                "seq": 2,
                "tool": "found_religion",
                "verifier_status": "PASS",
                "args": {
                    "religion_type": "RELIGION_CONFUCIANISM",
                    "follower_belief": "BELIEF_CHORAL_MUSIC",
                    "founder_belief": "BELIEF_PILGRIMAGE",
                },
                "payload": {
                    "result": "OK:RELIGION|RELIGION_CONFUCIANISM|BELIEF_CHORAL_MUSIC|BELIEF_PILGRIMAGE"
                },
            },
        ],
    )


def _make_execution_blocked_before_t25_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 25,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root / "raw" / "live_plan_events.jsonl",
        [
            _context_event(episode_id, 7, cities=1, era_score=4),
            _context_event(episode_id, 17, cities=1, era_score=9),
            _context_event(episode_id, 18, cities=1, era_score=9),
        ],
    )
    _write_jsonl(root / "raw" / "live_events.jsonl", [])


def _make_early_t25_milestone_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 25,
            }
        ),
        encoding="utf-8",
    )
    event = _context_event(episode_id, 23, cities=3, era_score=17)
    context = event["payload"]["context"]
    context["overview"]["total_population"] = 7
    context["cities"] = [
        {"city_id": 1, "name": "Xi'an", "x": 62, "y": 41, "currently_building": "UNIT_SETTLER"},
        {"city_id": 2, "name": "Yiyang", "x": 59, "y": 36, "currently_building": "NONE"},
        {"city_id": 3, "name": "Shanghai", "x": 65, "y": 37, "currently_building": "NONE"},
    ]
    context["units"] = [
        {"unit_id": 1, "unit_index": 1, "unit_type": "UNIT_WARRIOR", "x": 62, "y": 42},
        {"unit_id": 2, "unit_index": 2, "unit_type": "UNIT_SLINGER", "x": 59, "y": 36},
    ]
    context["resources"] = {"nearby": ["HORSES", "HORSES", "HORSES"]}
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [event])
    _write_jsonl(root / "raw" / "live_events.jsonl", [])


def _make_resumed_from_t31_checkpoint_episode(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "save_name": "HD_T50_v2_previous_T31_pass",
                "target_turn": 50,
                "start_turn": 31,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root / "raw" / "live_plan_events.jsonl",
        [
            _context_event(episode_id, 31, cities=3, era_score=21),
            _context_event(episode_id, 34, cities=3, era_score=21),
        ],
    )
    _write_jsonl(root / "raw" / "live_events.jsonl", [])


def test_human_demo_contract_records_all_checkpoint_obligations(tmp_path: Path) -> None:
    _make_failed_episode(tmp_path, "ep_contract_fail")

    report = evaluate_episode_contract("ep_contract_fail", workspace=tmp_path)

    assert report["contract_version"] == "human_demo_t50_reproduction_v2"
    assert len(report["checkpoints"]) == len(CHECKPOINTS)
    assert all(row["must_observe"] and row["failure_criteria"] for row in report["checkpoints"])
    assert "T16-T17" in report["attempt"]["critical_deviations"]
    assert report["final_targets"]["final_turn"] == 50
    assert report["final_target_results"]["final_turn"] is True
    assert report["final_target_results"]["num_cities"] is False
    assert report["attempt"]["success"] is False
    assert report["assumptions_and_stop_rules"] == ASSUMPTIONS_AND_STOP_RULES
    assert "stage_floor_acceptance" in report["assumptions_and_stop_rules"]
    assert "rollback_save_materialization" in report["assumptions_and_stop_rules"]


def test_human_demo_contract_accepts_final_metric_success_with_quality_gaps(tmp_path: Path) -> None:
    _make_final_metric_success_episode(tmp_path, "ep_final_metric_success")

    report = evaluate_episode_contract("ep_final_metric_success", workspace=tmp_path)

    assert all(report["final_target_results"].values())
    assert report["attempt"]["metrics_success"] is True
    assert report["attempt"]["causal_chain_complete"] is False
    assert report["attempt"]["success"] is True
    assert report["attempt"]["success_basis"] == "final_metrics_gte_reference_targets"


def test_human_demo_contract_preserves_full_v2_strategy_text() -> None:
    essentials_text = "\n".join(STRATEGY_ESSENTIALS)
    stages_text = "\n".join(str(stage["milestone"]) for stage in STAGES)

    for fragment in (
        "纪律/君主崇拜",
        "不是普通铺田",
        "缺任一环都只是表层模仿",
        "死海时代分",
        "与益阳同回合落地",
        "不靠总分碰运气",
        "T32 卖 14 马 + 开放边界换 100 金",
        "资源库存要转为即时产能/尤里卡/扩张",
        "T47-T49 上海/西安学院项目",
    ):
        assert fragment in essentials_text

    for fragment in (
        "投石兵开始外移",
        "西安不要继续 settler/builder rush",
        "时代分 7 -> 9",
        "城市数 1 -> 3",
        "T29 清益阳危机 +3、遇文明 +1",
        "目标是南京棉花/行业点",
        "科文约 12.5/14.9",
        "T49/T50 达到 4 城、人口 20、科技 20.8、文化 20.1",
    ):
        assert fragment in stages_text

    t50 = next(checkpoint for checkpoint in CHECKPOINTS if checkpoint["node"] == "T50")
    assert "科技 20.8" in t50["must_observe"]
    assert "文化 20.1" in t50["must_observe"]
    assert "时代分 31" in t50["must_observe"]
    assert "只满足 T50" in t50["failure_criteria"]


def test_human_demo_contract_markdown_renders_acceptance_rules(tmp_path: Path) -> None:
    _make_failed_episode(tmp_path, "ep_contract_markdown_rules")

    report = evaluate_episode_contract("ep_contract_markdown_rules", workspace=tmp_path)
    markdown = render_markdown(report)

    assert "## Acceptance Rules" in markdown
    assert "stage_floor_acceptance" in markdown
    assert "rollback_save_materialization" in markdown
    assert "major_bug_restart" in markdown
    assert "## Strategy Essentials" in markdown
    assert "T32 卖 14 马 + 开放边界换 100 金" in markdown
    assert "T47-T49 上海/西安学院项目" in markdown
    assert "| `final_turn` |" in markdown


def test_human_demo_contract_inherits_passed_rollback_checkpoint_nodes(tmp_path: Path) -> None:
    _make_resumed_from_t31_checkpoint_episode(tmp_path, "ep_resumed_t31")

    report = evaluate_episode_contract("ep_resumed_t31", workspace=tmp_path)

    assert report["evidence"]["inherited_checkpoint_turn"] == 31
    assert report["attempt"]["critical_deviations"] == []
    for node in ("T7", "T10", "T13", "T16-T17", "T20", "T25", "T29", "T31"):
        checkpoint = next(row for row in report["checkpoints"] if row["node"] == node)
        assert checkpoint["status"] == "pass"
        assert checkpoint["inherited_from_rollback"] is True

    t37 = next(row for row in report["checkpoints"] if row["node"] == "T37")
    assert t37.get("inherited_from_rollback") is not True


def test_human_demo_contract_requires_t13_chop_coordinate(tmp_path: Path) -> None:
    _make_wrong_chop_episode(tmp_path, "ep_wrong_chop")

    report = evaluate_episode_contract("ep_wrong_chop", workspace=tmp_path)

    t13 = next(row for row in report["checkpoints"] if row["node"] == "T13")
    chop = next(row for row in t13["observations"] if row["id"] == "forest_chop_63_40")
    assert chop["observed"] is False


def test_human_demo_contract_rejects_pre_window_religious_label_copy(tmp_path: Path) -> None:
    _make_pre_window_religion_episode(tmp_path, "ep_pre_window_religion")

    report = evaluate_episode_contract("ep_pre_window_religion", workspace=tmp_path)

    t17 = next(row for row in report["checkpoints"] if row["node"] == "T16-T17")
    t20 = next(row for row in report["checkpoints"] if row["node"] == "T20")
    religious_settlements = next(row for row in t17["observations"] if row["id"] == "religious_settlements")
    first_religion = next(row for row in t20["observations"] if row["id"] == "first_religion")
    choral_music = next(row for row in t20["observations"] if row["id"] == "choral_music")
    pilgrimage = next(row for row in t20["observations"] if row["id"] == "pilgrimage")
    assert religious_settlements["observed"] is False
    assert first_religion["observed"] is False
    assert choral_music["observed"] is False
    assert pilgrimage["observed"] is False


def test_human_demo_contract_does_not_count_unreached_stop_nodes(tmp_path: Path) -> None:
    _make_execution_blocked_before_t25_episode(tmp_path, "ep_blocked_t18")

    report = evaluate_episode_contract("ep_blocked_t18", workspace=tmp_path)

    assert "T25" not in report["attempt"]["critical_deviations"]
    assert "T29" not in report["attempt"]["critical_deviations"]
    t25 = next(row for row in report["checkpoints"] if row["node"] == "T25")
    assert t25["reached"] is False
    assert t25["critical_deviation"] is False
    assert report["final_target_results"]["final_turn"] is False


def test_human_demo_contract_accepts_stage_milestone_before_deadline(tmp_path: Path) -> None:
    _make_early_t25_milestone_episode(tmp_path, "ep_early_t25")

    report = evaluate_episode_contract("ep_early_t25", workspace=tmp_path)

    t25 = next(row for row in report["checkpoints"] if row["node"] == "T25")
    assert t25["status"] == "pass"
    assert t25["reached"] is True
    assert t25["deadline_turn"] == 25
    assert t25["achieved_turn"] == 23
    assert t25["critical_deviation"] is False


def test_human_demo_contract_rejects_loose_t25_city_alignment(tmp_path: Path) -> None:
    _make_early_t25_milestone_episode(tmp_path, "ep_loose_t25")
    event_path = tmp_path / "episodes" / "ep_loose_t25" / "raw" / "live_plan_events.jsonl"
    row = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    row["payload"]["context"]["cities"][1]["y"] = 37
    row["payload"]["context"]["cities"][2]["y"] = 39
    event_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    report = evaluate_episode_contract("ep_loose_t25", workspace=tmp_path)

    t25 = next(row for row in report["checkpoints"] if row["node"] == "T25")
    observations = {row["id"]: row for row in t25["observations"]}
    assert t25["status"] == "partial"
    assert observations["yiyang_equivalent"]["observed"] is False
    assert observations["shanghai_horse_lock"]["observed"] is False


def test_human_demo_contract_preserves_best_checkpoint_before_deadline(tmp_path: Path) -> None:
    episode_id = "ep_t29_best_before_deadline"
    root = tmp_path / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 29,
            }
        ),
        encoding="utf-8",
    )
    pass_event = _context_event(episode_id, 28, cities=3, era_score=19)
    pass_context = pass_event["payload"]["context"]
    pass_context["units"] = [
        {"unit_id": 2, "unit_index": 2, "unit_type": "UNIT_ARCHER", "x": 65, "y": 39},
    ]
    pass_context["threats"] = []
    later_event = _context_event(episode_id, 29, cities=3, era_score=19)
    later_context = later_event["payload"]["context"]
    later_context["units"] = pass_context["units"]
    later_context["threats"] = [{"unit_type": "UNIT_SCOUT"}, {"unit_type": "UNIT_SPEARMAN"}]
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [pass_event, later_event])
    _write_jsonl(
        root / "raw" / "live_events.jsonl",
        [
            {
                "event_type": "ACTION_FINISHED",
                "turn": 27,
                "seq": 1,
                "tool": "upgrade_unit",
                "verifier_status": "PASS",
                "args": {"upgrade_target": "UNIT_ARCHER"},
                "payload": {"result": "UPGRADED|UNIT_SLINGER -> UNIT_ARCHER"},
            },
            {
                "event_type": "ACTION_FINISHED",
                "turn": 28,
                "seq": 2,
                "tool": "unit_action",
                "verifier_status": "PASS",
                "args": {"action": "attack"},
                "payload": {"result": "RANGE_ATTACK|target:UNIT_SCOUT"},
            },
        ],
    )

    report = evaluate_episode_contract(episode_id, workspace=tmp_path)

    t29 = next(row for row in report["checkpoints"] if row["node"] == "T29")
    assert t29["status"] == "pass"
    assert t29["achieved_turn"] == 28
    assert t29["selected_context_turn"] == 28


def test_human_demo_contract_accepts_infrastructure_as_monumentality(tmp_path: Path) -> None:
    episode_id = "ep_t31_infrastructure"
    root = tmp_path / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 31,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [_context_event(episode_id, 31, cities=3, era_score=19)])
    _write_jsonl(
        root / "raw" / "live_events.jsonl",
        [
            {
                "event_type": "ACTION_FINISHED",
                "turn": 31,
                "seq": 1,
                "tool": "choose_dedication",
                "verifier_status": "PASS",
                "args": {"dedication_index": 3},
                "payload": {"result": "DEDICATION_CHOSEN|COMMEMORATION_INFRASTRUCTURE"},
            },
            {
                "event_type": "ACTION_FINISHED",
                "turn": 31,
                "seq": 2,
                "tool": "purchase_item",
                "verifier_status": "PASS",
                "args": {"yield_type": "YIELD_FAITH", "item_name": "UNIT_BUILDER"},
                "payload": {"result": "PURCHASED|UNIT_BUILDER|cost=50f"},
            },
        ],
    )

    report = evaluate_episode_contract(episode_id, workspace=tmp_path)

    t31 = next(row for row in report["checkpoints"] if row["node"] == "T31")
    assert t31["status"] == "pass"
    assert t31["achieved_turn"] == 31


def test_human_demo_contract_direct_actions_override_inherited_t31_save(tmp_path: Path) -> None:
    episode_id = "ep_t31_bad_action_with_false_pass_save"
    root = tmp_path / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "save_name": "HD_T50_v2_previous_T31_pass",
                "requested_turns": 31,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [_context_event(episode_id, 31, cities=3, era_score=19)])
    _write_jsonl(
        root / "raw" / "live_events.jsonl",
        [
            {
                "event_type": "ACTION_FINISHED",
                "turn": 31,
                "seq": 1,
                "tool": "choose_dedication",
                "verifier_status": "PASS",
                "payload": {"result": "DEDICATION_CHOSEN|COMMEMORATION_SCIENTIFIC"},
            },
            {
                "event_type": "ACTION_FINISHED",
                "turn": 31,
                "seq": 2,
                "tool": "purchase_item",
                "verifier_status": "PASS",
                "args": {"yield_type": "YIELD_FAITH", "item_name": "UNIT_BUILDER"},
                "payload": {"result": "PURCHASED|UNIT_BUILDER|cost=50f"},
            },
        ],
    )

    report = evaluate_episode_contract(episode_id, workspace=tmp_path)

    t31 = next(row for row in report["checkpoints"] if row["node"] == "T31")
    assert t31["status"] == "partial"
    assert t31.get("inherited_from_rollback") is not True


def test_human_demo_contract_ignores_unmaterialized_rollback_save_artifact(tmp_path: Path) -> None:
    episode_id = "ep_stale_t31_pass_artifact"
    root = tmp_path / "episodes" / episode_id
    root.mkdir(parents=True)
    store = EpisodeStore(root, episode_id)
    try:
        store.put_episode_header(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 31,
            }
        )
        store.replace_jsonl(
            "raw/live_plan_events.jsonl",
            [
                _context_event(episode_id, 31, cities=3, era_score=19),
            ],
        )
        store.replace_jsonl("raw/live_events.jsonl", [])
        store.put_binary_artifact(
            "raw/saves/HD_T50_v2_previous_T31_pass.Civ6Save",
            b"stale-save-only-in-sqlite",
            metadata={"checkpoint_node": "T31"},
        )
    finally:
        store.close()
    save_dir = root / "raw" / "saves"
    save_dir.mkdir(parents=True)
    (save_dir / "HD_T50_v2_previous_T31_INVALID_wrong_dedication.Civ6Save").write_bytes(
        b"renamed-invalid-save"
    )

    report = evaluate_episode_contract(episode_id, workspace=tmp_path)

    assert report["evidence"]["inherited_checkpoint_turn"] == 0
    assert not any(
        source.get("text") == "raw/saves/HD_T50_v2_previous_T31_pass.Civ6Save"
        for source in report["evidence"]["inherited_checkpoint_sources"]
    )
    t31 = next(row for row in report["checkpoints"] if row["node"] == "T31")
    assert t31.get("inherited_from_rollback") is not True


def test_human_demo_contract_accepts_monumentality_at_t31(tmp_path: Path) -> None:
    episode_id = "ep_t31_monumentality"
    root = tmp_path / "episodes" / episode_id
    root.mkdir(parents=True)
    (root / "header.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "strategy_profile": "human_demo_t50",
                "requested_turns": 31,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(root / "raw" / "live_plan_events.jsonl", [_context_event(episode_id, 31, cities=3, era_score=19)])
    _write_jsonl(
        root / "raw" / "live_events.jsonl",
        [
            {
                "event_type": "ACTION_FINISHED",
                "turn": 31,
                "seq": 1,
                "tool": "choose_dedication",
                "verifier_status": "PASS",
                "args": {"dedication_index": 4},
                "payload": {"result": "DEDICATION_CHOSEN|COMMEMORATION_MONUMENTALITY"},
            },
            {
                "event_type": "ACTION_FINISHED",
                "turn": 31,
                "seq": 2,
                "tool": "purchase_item",
                "verifier_status": "PASS",
                "args": {"yield_type": "YIELD_FAITH", "item_name": "UNIT_BUILDER"},
                "payload": {"result": "PURCHASED|UNIT_BUILDER|cost=50f"},
            },
        ],
    )

    report = evaluate_episode_contract(episode_id, workspace=tmp_path)

    t31 = next(row for row in report["checkpoints"] if row["node"] == "T31")
    assert t31["status"] == "pass"
    assert t31["achieved_turn"] == 31


def test_human_demo_contract_stop_rule_after_three_repeated_critical_failures(tmp_path: Path) -> None:
    for index in range(3):
        _make_failed_episode(tmp_path, f"ep_contract_fail_{index}")

    report = evaluate_attempt_window(
        [f"ep_contract_fail_{index}" for index in range(3)],
        workspace=tmp_path,
    )

    assert report["valid_attempt_count"] == 3
    assert report["stop_rule"]["stop_recommended"] is True
    assert "T16-T17" in report["stop_rule"]["repeated_critical_deviations"]


def test_human_demo_contract_window_markdown_renders_stage_scores_and_full_context(tmp_path: Path) -> None:
    for index in range(3):
        _make_failed_episode(tmp_path, f"ep_window_context_{index}")

    report = evaluate_attempt_window(
        [f"ep_window_context_{index}" for index in range(3)],
        workspace=tmp_path,
    )
    markdown = render_markdown(report)

    assert report["strategy_essentials"] == STRATEGY_ESSENTIALS
    assert report["assumptions_and_stop_rules"] == ASSUMPTIONS_AND_STOP_RULES
    assert "## Acceptance Rules" in markdown
    assert "## Strategy Essentials" in markdown
    assert "## Stage Scores" in markdown
    assert "Final Turn" in markdown
    assert "`T1-T7`" in markdown
    assert "`T47-T50`" in markdown
    assert "T32 卖 14 马 + 开放边界换 100 金" in markdown
