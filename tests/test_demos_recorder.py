import asyncio
import sqlite3
import tomllib

from codex_hl.demos import recorder
from codex_hl.demos.cli import (
    _watch_transition_status,
    parse_args,
    run_correct,
    run_record_inference,
    run_report_only,
)


def test_sqlite_demo_schema_initializes_session(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        row = demo.conn.execute("SELECT * FROM demo_sessions").fetchone()
        assert row["demo_id"] == "demo_test"
        assert row["save_name"] == "test 1"
        assert row["status"] == "running"
        assert row["schema_version"] == recorder.SCHEMA_VERSION
        columns = {
            row["name"]
            for row in demo.conn.execute("PRAGMA table_info(human_actions)").fetchall()
        }
        assert {
            "inferred_summary",
            "confidence",
            "needs_review",
            "user_correction",
            "evidence_json",
            "status",
        }.issubset(columns)
        fact_columns = {
            row["name"]
            for row in demo.conn.execute("PRAGMA table_info(action_facts)").fetchall()
        }
        assert {
            "fact_id",
            "action_id",
            "category",
            "kind",
            "subject_id",
            "subject_name",
            "metric",
            "before_json",
            "after_json",
            "delta_json",
            "summary",
        }.issubset(fact_columns)
    finally:
        demo.close()


def test_record_human_turn_transaction_writes_action_and_delta(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before = {
            "turn": 1,
            "overview": {"turn": 1, "num_cities": 1, "science_yield": 2},
            "cities": [{"city_id": 10, "name": "Capital", "population": 1}],
            "units": [{"unit_id": 7, "unit_type": "UNIT_WARRIOR", "x": 1, "y": 2}],
        }
        after = {
            "turn": 2,
            "overview": {"turn": 2, "num_cities": 1, "science_yield": 3},
            "cities": [{"city_id": 10, "name": "Capital", "population": 2}],
            "units": [{"unit_id": 7, "unit_type": "UNIT_WARRIOR", "x": 2, "y": 2}],
        }
        before_id = demo.record_state(1, "turn_001_before", before, ["tool-00001"])
        after_id = demo.record_state(2, "turn_001_after", after, ["tool-00002"])
        delta = recorder.build_state_delta(before, after)

        action_id = demo.record_human_turn(
            turn=1,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            summary="moved warrior and kept building",
            rationale="reveal safer tiles before settling",
            tags=["scouting"],
            delta=delta,
        )

        assert action_id == "human-action-0001"
        action_count = demo.conn.execute("SELECT COUNT(*) AS n FROM human_actions").fetchone()["n"]
        delta_count = demo.conn.execute("SELECT COUNT(*) AS n FROM state_deltas").fetchone()["n"]
        fact_count = demo.conn.execute("SELECT COUNT(*) AS n FROM action_facts").fetchone()["n"]
        assert action_count == 1
        assert delta_count == 1
        assert fact_count >= 2
        row = demo.conn.execute("SELECT * FROM human_actions").fetchone()
        assert row["confidence"] == "manual"
        assert row["needs_review"] == 0
        kinds = {
            row["kind"]
            for row in demo.conn.execute("SELECT kind FROM action_facts").fetchall()
        }
        assert {"overview_metric_changed", "unit_moved"}.issubset(kinds)
    finally:
        demo.close()


def test_pending_before_snapshot_detection(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before_id = demo.record_state(
            1,
            "turn_001_before",
            {"turn": 1, "overview": {"turn": 1}},
            [],
        )
        pending = demo.pending_before_snapshots()
        assert [row["snapshot_id"] for row in pending] == [before_id]
    finally:
        demo.close()


def test_clone_after_snapshot_as_next_before(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        after_id = demo.record_state(
            2,
            "turn_001_after",
            {"turn": 2, "overview": {"turn": 2}, "units": []},
            ["tool-00002"],
        )
        before_id = demo.clone_state_snapshot(after_id, "turn_002_before")
        pending = demo.pending_before_snapshots()
        loaded = demo.load_snapshot(before_id)
        assert [row["snapshot_id"] for row in pending] == [before_id]
        assert loaded["snapshot_id"] == before_id
        assert loaded["label"] == "turn_002_before"
        assert loaded["related_tool_call_ids"] == ["tool-00002"]
    finally:
        demo.close()


def test_report_only_generates_html_from_sqlite(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before = {"turn": 1, "overview": {"turn": 1, "science_yield": 2}}
        after = {"turn": 2, "overview": {"turn": 2, "science_yield": 3}}
        before_id = demo.record_state(1, "turn_001_before", before, [])
        after_id = demo.record_state(2, "turn_001_after", after, [])
        demo.record_human_turn(
            turn=1,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            summary="picked a safer opening",
            rationale="avoid exposing the warrior",
            tags=["defense"],
            delta=recorder.build_state_delta(before, after),
        )
        demo.complete_session()
    finally:
        demo.close()

    args = parse_args(["--report-only", "--db", str(db_path)])
    payload = run_report_only(args)
    report_path = tmp_path / "report.html"
    assert payload["report_path"] == str(report_path)
    text = report_path.read_text(encoding="utf-8")
    assert "人类操作录制报告" in text
    assert "picked a safer opening" in text
    assert "低置信 / 待复核回合" in text
    assert "结构化变化明细" in text
    assert "科技值 2 -&gt; 3" in text


def test_tool_call_logs_to_sqlite(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )

    async def run_call():
        return await demo.tool_call("get_fake_tool", {"x": 1}, lambda: _fake_async_result())

    try:
        call_id, result = asyncio.run(run_call())
        assert call_id == "tool-00001"
        assert result == {"ok": True}
        row = demo.conn.execute("SELECT * FROM tool_calls").fetchone()
        assert row["tool"] == "get_fake_tool"
        assert row["success"] == 1
    finally:
        demo.close()


def test_human_demo_refuses_write_tools(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )

    async def run_call():
        return await demo.tool_call("end_turn", {}, lambda: _fake_async_result())

    try:
        try:
            asyncio.run(run_call())
        except recorder.HumanDemoError as exc:
            assert "strict read-only" in str(exc)
        else:
            raise AssertionError("end_turn should be refused in human demo recording")
    finally:
        demo.close()


async def _fake_async_result():
    return {"ok": True}


def test_project_metadata_includes_human_demo_command():
    pyproject = tomllib.loads((recorder.ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert (
        scripts["codex-hl-civ6-human-demo-record"]
        == "codex_hl.demos.cli:main"
    )


def test_human_demo_db_uses_declared_tables(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert {
            "demo_sessions",
            "state_snapshots",
            "human_actions",
            "state_deltas",
            "action_facts",
            "tool_calls",
            "lua_exchanges",
            "manual_notes",
            "inference_audit",
        }.issubset(tables)
    finally:
        demo.close()


def test_rule_inference_extracts_unit_move_and_city_production():
    before = {
        "turn": 1,
        "overview": {"turn": 1, "science_yield": 2},
        "cities": [
            {
                "city_id": 10,
                "name": "Capital",
                "current_production": "Warrior",
                "population": 1,
            }
        ],
        "units": [{"unit_id": 7, "unit_type": "UNIT_WARRIOR", "x": 1, "y": 2}],
    }
    after = {
        "turn": 2,
        "overview": {"turn": 2, "science_yield": 3},
        "cities": [
            {
                "city_id": 10,
                "name": "Capital",
                "current_production": "Monument",
                "population": 1,
            }
        ],
        "units": [{"unit_id": 7, "unit_type": "UNIT_WARRIOR", "x": 2, "y": 2}],
    }

    rule = recorder.build_rule_inference(recorder.build_state_delta(before, after))

    assert rule["confidence"] == "high"
    assert "单位 7" in rule["summary"]
    assert "current_production" in rule["summary"]
    assert rule["needs_review"] is False


def test_action_facts_capture_t1_strategy_and_metrics():
    before = {
        "turn": 1,
        "overview": {
            "turn": 1,
            "num_cities": 0,
            "num_units": 2,
            "science_yield": 0.0,
            "culture_yield": 0.0,
            "gold": 5.0,
            "gold_per_turn": 0.0,
            "gold_income": 0.0,
            "score": 0,
            "total_population": 0,
            "current_research": "None",
            "current_civic": "法典",
        },
        "research_civic": {
            "current_research": "None",
            "current_research_turns": -1,
            "current_civic": "法典",
            "current_civic_turns": -1,
            "available_techs": [
                {"name": "占星术", "tech_type": "TECH_ASTROLOGY", "turns": -1, "progress_pct": 0}
            ],
            "available_civics": [
                {"name": "法典", "civic_type": "CIVIC_CODE_OF_LAWS", "turns": -1, "progress_pct": 0}
            ],
        },
        "cities": [],
        "units": [
            {"unit_id": 65536, "unit_type": "开拓者", "x": 62, "y": 41},
            {"unit_id": 131073, "unit_type": "勇士", "x": 62, "y": 42},
        ],
    }
    after = {
        "turn": 2,
        "overview": {
            "turn": 2,
            "num_cities": 1,
            "num_units": 1,
            "science_yield": 2.5,
            "culture_yield": 1.3,
            "gold": 10.0,
            "gold_per_turn": 5.0,
            "gold_income": 5.0,
            "score": 7,
            "total_population": 1,
            "current_research": "占星术",
            "current_civic": "法典",
        },
        "research_civic": {
            "current_research": "占星术",
            "current_research_turns": 9,
            "current_civic": "法典",
            "current_civic_turns": 7,
            "available_techs": [
                {"name": "占星术", "tech_type": "TECH_ASTROLOGY", "turns": 9, "progress_pct": 10}
            ],
            "available_civics": [
                {"name": "法典", "civic_type": "CIVIC_CODE_OF_LAWS", "turns": 7, "progress_pct": 0}
            ],
        },
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "x": 62,
                "y": 41,
                "population": 1,
                "housing": 6.0,
                "amenities": 3,
                "currently_building": "UNIT_SLINGER",
                "production_turns_left": 4,
            }
        ],
        "units": [
            {"unit_id": 131073, "unit_type": "勇士", "x": 62, "y": 40}
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)
    by_kind = {(fact["kind"], fact.get("metric")): fact for fact in facts}

    assert by_kind[("tech_selected", "current_research")]["subject_name"] == "占星术"
    assert by_kind[("civic_selected", "current_civic")]["subject_name"] == "法典"
    assert by_kind[("production_selected", "currently_building")]["after"]["currently_building"] == "UNIT_SLINGER"
    assert by_kind[("overview_metric_changed", "science_yield")]["delta"] == 2.5
    assert by_kind[("overview_metric_changed", "culture_yield")]["delta"] == 1.3
    assert by_kind[("overview_metric_changed", "gold")]["delta"] == 5.0
    assert by_kind[("overview_metric_changed", "gold_per_turn")]["delta"] == 5.0
    assert by_kind[("overview_metric_changed", "gold_income")]["delta"] == 5.0
    assert any(fact["kind"] == "city_added" and fact["subject_name"] == "西安" for fact in facts)
    assert any(
        fact["kind"] == "city_founded_by_settler" and fact["subject_name"] == "西安"
        for fact in facts
    )
    assert any(fact["kind"] == "unit_removed" and fact["subject_name"] == "开拓者" for fact in facts)
    assert any(fact["summary"] == "开拓者 用于建立城市 西安" for fact in facts)
    assert any(fact["kind"] == "unit_moved" and fact["subject_name"] == "勇士" for fact in facts)
    assert "占星术" in rule["summary"]
    assert "法典" in rule["summary"]
    assert "UNIT_SLINGER" in rule["summary"]
    assert "勇士" in rule["summary"]


def test_rule_inference_prioritizes_era_score_for_golden_age_path():
    before = {
        "turn": 4,
        "overview": {
            "turn": 4,
            "science_yield": 2.5,
            "culture_yield": 1.3,
            "gold": 20.0,
            "score": 7,
            "era_score": 0,
            "era_golden_threshold": 19,
        },
        "research_civic": {
            "current_research": "占星术",
            "current_research_turns": 7,
            "current_civic": "法典",
            "current_civic_turns": 5,
        },
        "cities": [
            {"city_id": 1, "name": "西安", "currently_building": "UNIT_SLINGER", "production_turns_left": 2}
        ],
        "units": [{"unit_id": 1, "unit_type": "勇士", "x": 61, "y": 38}],
    }
    after = {
        "turn": 5,
        "overview": {
            "turn": 5,
            "science_yield": 3.0,
            "culture_yield": 1.6,
            "gold": 25.0,
            "score": 10,
            "era_score": 3,
            "era_golden_threshold": 19,
        },
        "research_civic": {
            "current_research": "占星术",
            "current_research_turns": 2,
            "current_civic": "法典",
            "current_civic_turns": 4,
        },
        "cities": [
            {"city_id": 1, "name": "西安", "currently_building": "UNIT_SLINGER", "production_turns_left": 1}
        ],
        "units": [{"unit_id": 1, "unit_type": "勇士", "x": 60, "y": 36}],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)
    era_fact = next(
        fact
        for fact in facts
        if fact["kind"] == "overview_metric_changed" and fact["metric"] == "era_score"
    )

    assert era_fact["importance"] == "high"
    assert "时代分 0 -> 3" in era_fact["summary"]
    assert "黄金门槛 19" in era_fact["summary"]
    assert "距黄金时代差 16" in era_fact["summary"]
    assert "时代分 0 -> 3" in rule["summary"]


def test_action_facts_capture_policy_slot_assignments():
    before = {
        "turn": 9,
        "overview": {"turn": 9},
        "policies": {
            "government_name": "酋邦",
            "government_type": "GOVERNMENT_CHIEFDOM",
            "slots": [
                {
                    "slot_index": 0,
                    "slot_type": "SLOT_MILITARY",
                    "current_policy": None,
                    "current_policy_name": None,
                },
                {
                    "slot_index": 1,
                    "slot_type": "SLOT_ECONOMIC",
                    "current_policy": None,
                    "current_policy_name": None,
                },
            ],
        },
    }
    after = {
        "turn": 10,
        "overview": {"turn": 10},
        "policies": {
            "government_name": "酋邦",
            "government_type": "GOVERNMENT_CHIEFDOM",
            "slots": [
                {
                    "slot_index": 0,
                    "slot_type": "SLOT_MILITARY",
                    "current_policy": "POLICY_DISCIPLINE",
                    "current_policy_name": "纪律",
                },
                {
                    "slot_index": 1,
                    "slot_type": "SLOT_ECONOMIC",
                    "current_policy": "POLICY_GOD_KING",
                    "current_policy_name": "君主崇拜",
                },
            ],
        },
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)

    assert delta["policies_changed"] is True
    assert delta["policies"]["changed"]["0"]["after"]["current_policy_name"] == "纪律"
    assert delta["policies"]["changed"]["1"]["after"]["current_policy_name"] == "君主崇拜"
    assert {
        fact["summary"]
        for fact in facts
        if fact["kind"] == "policy_changed"
    } == {
        "政策槽 SLOT_MILITARY 空 -> 纪律",
        "政策槽 SLOT_ECONOMIC 空 -> 君主崇拜",
    }
    assert "政策槽 SLOT_MILITARY 空 -> 纪律" in rule["summary"]
    assert "政策槽 SLOT_ECONOMIC 空 -> 君主崇拜" in rule["summary"]


def test_action_facts_capture_historic_moment_additions():
    before = {
        "turn": 10,
        "overview": {"turn": 10, "era_score": 4, "era_golden_threshold": 19},
        "historic_moments": [],
    }
    after = {
        "turn": 11,
        "overview": {"turn": 11, "era_score": 7, "era_golden_threshold": 19},
        "historic_moments": [
            {
                "moment_id": 20,
                "turn": 10,
                "moment_type": "MOMENT_PLAYER_MET_MAJOR",
                "instance_description": "在好奇与警惕中，我们遇见了白板文明 (12)的人民。",
                "era_score": 1,
            },
            {
                "moment_id": 22,
                "turn": 10,
                "moment_type": "MOMENT_BARBARIAN_CAMP_DESTROYED",
                "instance_description": "我方军队摧毁了一个蛮族营地，阻碍文明发展的威胁已清除。",
                "era_score": 2,
            },
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)
    historic = [fact for fact in facts if fact["kind"] == "historic_moment_added"]

    assert delta["historic_moments"]["added"] == ["20", "22"]
    assert [fact["delta"] for fact in historic] == [1, 2]
    assert "历史时刻 +1: 在好奇与警惕中，我们遇见了白板文明 (12)的人民。" in rule["summary"]
    assert "历史时刻 +2: 我方军队摧毁了一个蛮族营地" in rule["summary"]


def test_action_facts_capture_builder_charge_use():
    before = {
        "turn": 13,
        "overview": {"turn": 13},
        "units": [
            {
                "unit_id": 262146,
                "unit_type": "UNIT_BUILDER",
                "name": "建造者",
                "x": 63,
                "y": 40,
                "build_charges": 2,
            }
        ],
    }
    after = {
        "turn": 14,
        "overview": {"turn": 14},
        "units": [
            {
                "unit_id": 262146,
                "unit_type": "UNIT_BUILDER",
                "name": "建造者",
                "x": 63,
                "y": 40,
                "build_charges": 1,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)
    builder = [fact for fact in facts if fact["kind"] == "builder_charge_used"]

    assert builder == [
        {
            "category": "builder",
            "kind": "builder_charge_used",
            "subject_id": "262146",
            "subject_name": "建造者",
            "metric": "build_charges",
            "before": 2,
            "after": 1,
            "delta": -1,
            "summary": "建造者 消耗 1 次建造次数（2 -> 1）",
            "importance": "high",
            "source": "snapshot_delta",
        }
    ]
    assert "建造者 消耗 1 次建造次数（2 -> 1）" in rule["summary"]


def test_action_facts_capture_builder_resource_improvement():
    before = {
        "turn": 32,
        "overview": {"turn": 32},
        "cities": [
            {
                "city_id": 196610,
                "name": "上海",
                "unimproved_resources": ["HORSES@65", "36", "HORSES@66", "38"],
            }
        ],
        "units": [
            {
                "unit_id": 720898,
                "unit_type": "UNIT_BUILDER",
                "name": "建造者",
                "x": 65,
                "y": 37,
                "build_charges": 3,
            }
        ],
    }
    after = {
        "turn": 33,
        "overview": {"turn": 33},
        "cities": [
            {
                "city_id": 196610,
                "name": "上海",
                "unimproved_resources": ["HORSES@66", "38"],
            }
        ],
        "units": [
            {
                "unit_id": 720898,
                "unit_type": "UNIT_BUILDER",
                "name": "建造者",
                "x": 65,
                "y": 36,
                "build_charges": 2,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    improved = [fact for fact in facts if fact["kind"] == "builder_resource_improved"]

    assert len(improved) == 1
    assert improved[0]["summary"] == "建造者 在 (65,36) 改良 HORSES（上海）"
    assert improved[0]["before"]["resource"] == "HORSES"


def test_action_facts_record_completed_production_without_idle_selection():
    before = {
        "turn": 14,
        "overview": {"turn": 14},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "PROJECT_ENHANCE_DISTRICT_HOLY_SITE",
                "production_turns_left": 1,
            }
        ],
    }
    after = {
        "turn": 15,
        "overview": {"turn": 15},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "nothing",
                "production_turns_left": 0,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)
    production = [fact for fact in facts if fact["category"] == "production"]

    assert [fact["kind"] for fact in production] == ["production_completed"]
    assert production[0]["summary"] == (
        "西安 完成或结束 PROJECT_ENHANCE_DISTRICT_HOLY_SITE，当前待选择生产"
    )
    assert "生产 nothing" not in rule["summary"]


def test_action_facts_do_not_mark_unobserved_building_as_completed():
    before = {
        "turn": 22,
        "overview": {"turn": 22},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "BUILDING_MONUMENT",
                "production_turns_left": 5,
                "buildings": ["PALACE"],
            }
        ],
    }
    after = {
        "turn": 22,
        "overview": {"turn": 22},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "nothing",
                "production_turns_left": 0,
                "buildings": ["PALACE"],
            }
        ],
        "notifications": [
            {
                "type_name": "NOTIFICATION_CHOOSE_CITY_PRODUCTION",
                "is_action_required": True,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)
    production = [fact for fact in facts if fact["category"] == "production"]

    assert [fact["kind"] for fact in production] == ["production_pending"]
    assert production[0]["summary"] == "西安 当前待选择生产；未确认完成 BUILDING_MONUMENT"
    assert "完成或结束 BUILDING_MONUMENT" not in rule["summary"]


def test_action_facts_match_completed_building_without_prefix():
    before = {
        "turn": 27,
        "overview": {"turn": 27},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "BUILDING_SHRINE",
                "production_turns_left": 1,
                "buildings": ["PALACE"],
            }
        ],
    }
    after = {
        "turn": 29,
        "overview": {"turn": 29},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "DISTRICT_CAMPUS",
                "production_turns_left": 7,
                "buildings": ["PALACE", "SHRINE"],
                "districts": ["DISTRICT_HOLY_SITE@63,39", "DISTRICT_CAMPUS@63,40"],
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    production = [fact for fact in facts if fact["category"] == "production"]

    assert [fact["kind"] for fact in production] == [
        "production_completed",
        "production_selected",
    ]
    assert production[0]["summary"] == (
        "西安 完成 BUILDING_SHRINE，随后生产 DISTRICT_CAMPUS（7回合）"
    )


def test_action_facts_capture_completed_unit_and_next_production():
    before = {
        "turn": 21,
        "overview": {"turn": 21},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "UNIT_SETTLER",
                "production_turns_left": 1,
            }
        ],
        "units": [],
    }
    after = {
        "turn": 22,
        "overview": {"turn": 22},
        "cities": [
            {
                "city_id": 65536,
                "name": "西安",
                "currently_building": "BUILDING_MONUMENT",
                "production_turns_left": 5,
            }
        ],
        "units": [
            {
                "unit_id": 524292,
                "name": "开拓者",
                "unit_type": "UNIT_SETTLER",
                "x": 64,
                "y": 40,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    production = [fact for fact in facts if fact["category"] == "production"]

    assert [fact["kind"] for fact in production] == [
        "production_completed",
        "production_selected",
    ]
    assert production[0]["summary"] == (
        "西安 完成 UNIT_SETTLER，随后生产 BUILDING_MONUMENT（5回合）"
    )
    assert production[1]["summary"] == "西安 生产 BUILDING_MONUMENT（5回合）"


def test_action_facts_infer_unit_purchase_from_gold_and_added_unit():
    before = {
        "turn": 22,
        "overview": {"turn": 22, "gold": 62.0, "gold_per_turn": 7.0},
        "production": {
            "65536": [
                {"item_name": "UNIT_SCOUT", "gold_cost": 60},
            ]
        },
        "units": [],
    }
    after = {
        "turn": 23,
        "overview": {"turn": 23, "gold": 9.0, "gold_per_turn": 7.0},
        "units": [
            {
                "unit_id": 589824,
                "name": "侦察兵",
                "unit_type": "UNIT_SCOUT",
                "x": 62,
                "y": 41,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    purchases = [fact for fact in facts if fact["kind"] == "unit_purchased"]

    assert len(purchases) == 1
    assert purchases[0]["subject_name"] == "侦察兵"
    assert purchases[0]["delta"] == {"gold_spent": 60.0, "net_gold_delta": -53.0}
    assert purchases[0]["summary"] == "花费约 60 金币购买侦察兵（金币 62 -> 9）"


def test_action_facts_infer_faith_purchase_for_civilian_units():
    before = {
        "turn": 31,
        "overview": {"turn": 31, "faith": 81.8, "faith_per_turn": 9.8},
        "cities": [
            {"name": "Xian", "faith": 4.0},
            {"name": "Yiyang", "faith": 1.8},
            {"name": "Shanghai", "faith": 4.0},
        ],
        "units": [],
    }
    after = {
        "turn": 32,
        "overview": {"turn": 32, "faith": 11.6},
        "units": [
            {
                "unit_id": 720898,
                "name": "Builder",
                "unit_type": "UNIT_BUILDER",
                "x": 65,
                "y": 37,
            },
            {
                "unit_id": 786435,
                "name": "Trader",
                "unit_type": "UNIT_TRADER",
                "x": 59,
                "y": 36,
            },
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    purchases = [
        fact for fact in facts if fact["kind"] == "faith_civilian_units_purchased"
    ]

    assert len(purchases) == 1
    assert purchases[0]["subject_name"] == "Builder、Trader"
    assert purchases[0]["delta"] == {
        "faith_spent_estimate": 80.0,
        "net_faith_delta": -70.2,
        "unit_count": 2,
        "unit_types": ["UNIT_BUILDER", "UNIT_TRADER"],
    }


def test_action_facts_infer_unit_upgrade_and_completed_tech():
    before = {
        "turn": 26,
        "overview": {"turn": 26, "gold": 30.9, "gold_per_turn": 7.9},
        "research_civic": {
            "current_research": "箭术",
            "current_research_turns": 1,
            "available_techs": [
                {"name": "箭术", "tech_type": "TECH_ARCHERY", "progress_pct": 95},
            ],
        },
        "units": [
            {
                "unit_id": 393218,
                "name": "投石兵",
                "unit_type": "UNIT_SLINGER",
                "x": 59,
                "y": 36,
                "combat_strength": 5,
                "ranged_strength": 15,
            }
        ],
    }
    after = {
        "turn": 27,
        "overview": {"turn": 27, "gold": 8.8, "gold_per_turn": 6.9},
        "research_civic": {
            "current_research": "骑马",
            "current_research_turns": 14,
            "available_techs": [
                {"name": "骑马", "tech_type": "TECH_HORSEBACK_RIDING", "progress_pct": 0},
            ],
        },
        "units": [
            {
                "unit_id": 655364,
                "name": "弓箭手",
                "unit_type": "UNIT_ARCHER",
                "x": 59,
                "y": 36,
                "combat_strength": 15,
                "ranged_strength": 25,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    by_kind = {fact["kind"]: fact for fact in facts}

    assert by_kind["tech_completed"]["summary"] == "科技完成 箭术，随后选择 骑马"
    assert by_kind["unit_upgraded"]["summary"] == "花费约 30 金币将投石兵升级为弓箭手"
    assert by_kind["unit_upgraded"]["delta"]["gold_spent_estimate"] == 30.0
    assert any(fact["summary"] == "投石兵 已升级为 弓箭手" for fact in facts)


def test_action_facts_infer_completed_tech_from_completed_count():
    before = {
        "turn": 32,
        "overview": {"turn": 32, "current_research": "骑马"},
        "research_civic": {
            "completed_tech_count": 6,
            "current_research": "骑马",
            "current_research_turns": 5,
            "available_techs": [
                {
                    "name": "骑马",
                    "tech_type": "TECH_HORSEBACK_RIDING",
                    "progress_pct": 53,
                }
            ],
        },
    }
    after = {
        "turn": 33,
        "overview": {"turn": 33, "current_research": "None"},
        "research_civic": {
            "completed_tech_count": 7,
            "current_research": "None",
            "current_research_turns": -1,
            "available_techs": [],
        },
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    completed = [fact for fact in facts if fact["kind"] == "tech_completed"]

    assert len(completed) == 1
    assert completed[0]["summary"] == "科技完成 骑马，等待后续选择"
    assert completed[0]["source"] == "before_snapshot+after_snapshot+completed_count"


def test_action_facts_capture_research_boosts():
    before = {
        "turn": 32,
        "overview": {"turn": 32},
        "research_civic": {
            "available_techs": [
                {
                    "name": "货币",
                    "tech_type": "TECH_CURRENCY",
                    "boosted": False,
                    "boost_desc": "建立1条贸易路线。",
                    "progress_pct": 0,
                }
            ]
        },
    }
    after = {
        "turn": 33,
        "overview": {"turn": 33},
        "research_civic": {
            "available_techs": [
                {
                    "name": "货币",
                    "tech_type": "TECH_CURRENCY",
                    "boosted": True,
                    "boost_desc": "建立1条贸易路线。",
                    "progress_pct": 38,
                }
            ]
        },
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    boosted = [fact for fact in facts if fact["kind"] == "tech_boosted"]

    assert len(boosted) == 1
    assert boosted[0]["summary"] == "科技触发尤里卡/鼓舞 货币（建立1条贸易路线。），进度 0 -> 38"
    assert boosted[0]["delta"] == {"boosted": True}


def test_action_facts_capture_religious_settlements_pantheon():
    before = {
        "turn": 16,
        "overview": {"turn": 16},
        "pantheon_status": {
            "has_pantheon": False,
            "current_belief": None,
            "current_belief_name": None,
        },
        "units": [],
    }
    after = {
        "turn": 17,
        "overview": {"turn": 17},
        "pantheon_status": {
            "has_pantheon": True,
            "current_belief": "BELIEF_RELIGIOUS_SETTLEMENTS",
            "current_belief_name": "宗教移民",
        },
        "units": [
            {
                "unit_id": 327683,
                "unit_type": "UNIT_SETTLER",
                "name": "开拓者",
                "x": 61,
                "y": 40,
            }
        ],
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    rule = recorder.build_rule_inference(delta, facts=facts)

    assert [fact["kind"] for fact in facts if fact["category"] == "religion"] == [
        "pantheon_selected",
        "religious_settlements_free_settler",
    ]
    assert "万神殿选择 宗教移民" in rule["summary"]
    assert "宗教移民触发免费开拓者" in rule["summary"]


def test_missing_optional_snapshot_fields_do_not_create_change_facts():
    before = {
        "turn": 14,
        "overview": {"turn": 14},
        "resources": {"iron": 0},
        "diplomacy": {"met_players": ["A"]},
        "victory": {"score_rank": 1},
        "strategic_map": {"tiles": [{"x": 1, "y": 2}]},
        "notifications": [{"id": 1}],
        "threats": [{"kind": "barbarian"}],
    }
    after = {
        "turn": 15,
        "overview": {"turn": 15},
        "resources": None,
        "diplomacy": None,
        "victory": None,
        "strategic_map": None,
        "notifications": None,
        "threats": None,
    }

    delta = recorder.build_state_delta(before, after)
    facts = recorder.extract_action_facts(before, after, delta)
    fact_kinds = {fact["kind"] for fact in facts}

    assert delta["resources_changed"] is False
    assert delta["diplomacy_changed"] is False
    assert delta["victory_changed"] is False
    assert delta["map_changed"] is False
    assert delta["risk"]["notifications"]["observed"] is False
    assert delta["risk"]["notifications"]["delta"] == 0
    assert "resource_changed" not in fact_kinds
    assert "diplomacy_changed" not in fact_kinds
    assert "victory_changed" not in fact_kinds
    assert "map_changed" not in fact_kinds
    assert "risk_changed" not in fact_kinds


def test_record_human_turn_writes_action_facts_for_sql_queries(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before = {
            "turn": 1,
            "overview": {"turn": 1, "science_yield": 0.0, "culture_yield": 0.0},
            "research_civic": {"current_research": "None", "current_civic": "法典"},
            "cities": [],
            "units": [{"unit_id": 1, "unit_type": "勇士", "x": 1, "y": 1}],
        }
        after = {
            "turn": 2,
            "overview": {"turn": 2, "science_yield": 2.5, "culture_yield": 1.3},
            "research_civic": {
                "current_research": "占星术",
                "current_research_turns": 9,
                "current_civic": "法典",
                "current_civic_turns": 7,
                "available_techs": [{"name": "占星术", "tech_type": "TECH_ASTROLOGY", "progress_pct": 10}],
                "available_civics": [{"name": "法典", "civic_type": "CIVIC_CODE_OF_LAWS", "progress_pct": 0}],
            },
            "cities": [
                {"city_id": 10, "name": "西安", "currently_building": "UNIT_SLINGER", "production_turns_left": 4}
            ],
            "units": [{"unit_id": 1, "unit_type": "勇士", "x": 2, "y": 1}],
        }
        before_id = demo.record_state(1, "turn_001_before", before, [])
        after_id = demo.record_state(2, "turn_001_after", after, [])
        delta = recorder.build_state_delta(before, after)
        facts = recorder.extract_action_facts(before, after, delta)
        action_id = demo.record_human_turn(
            turn=1,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            summary="pending",
            rationale="pending",
            tags=[],
            delta=delta,
            facts=facts,
        )
        rows = demo.conn.execute(
            """
            SELECT kind, subject_name, metric, after_json, delta_json
            FROM action_facts
            WHERE action_id = ?
            """,
            (action_id,),
        ).fetchall()
        facts_from_db = {(row["kind"], row["metric"]): row for row in rows}

        assert facts_from_db[("tech_selected", "current_research")]["subject_name"] == "占星术"
        assert facts_from_db[("civic_selected", "current_civic")]["subject_name"] == "法典"
        assert "UNIT_SLINGER" in facts_from_db[("production_selected", "currently_building")]["after_json"]
        assert facts_from_db[("overview_metric_changed", "science_yield")]["delta_json"] == "2.5"
    finally:
        demo.close()


def test_record_human_turn_rolls_back_when_fact_insert_fails(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before = {"turn": 1, "overview": {"turn": 1}}
        after = {"turn": 2, "overview": {"turn": 2}}
        before_id = demo.record_state(1, "turn_001_before", before, [])
        after_id = demo.record_state(2, "turn_001_after", after, [])
        try:
            demo.record_human_turn(
                turn=1,
                before_snapshot_id=before_id,
                after_snapshot_id=after_id,
                summary="pending",
                rationale="pending",
                tags=[],
                delta=recorder.build_state_delta(before, after),
                facts=[{"category": "broken", "kind": "broken", "importance": "low"}],
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("missing fact summary should fail the transaction")

        assert demo.conn.execute("SELECT COUNT(*) FROM human_actions").fetchone()[0] == 0
        assert demo.conn.execute("SELECT COUNT(*) FROM state_deltas").fetchone()[0] == 0
        assert demo.conn.execute("SELECT COUNT(*) FROM action_facts").fetchone()[0] == 0
    finally:
        demo.close()


def test_record_inference_and_correction_cli_update_sqlite(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before = {"turn": 1, "overview": {"turn": 1}}
        after = {"turn": 2, "overview": {"turn": 2}}
        before_id = demo.record_state(1, "turn_001_before", before, [])
        after_id = demo.record_state(2, "turn_001_after", after, [])
        action_id = demo.record_human_turn(
            turn=1,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            summary="pending",
            rationale="pending",
            tags=[],
            delta=recorder.build_state_delta(before, after),
            confidence="low",
            needs_review=True,
            status="pending_codex_inference",
        )
    finally:
        demo.close()

    args = parse_args(
        [
            "record-inference",
            "--db",
            str(db_path),
            "--action-id",
            action_id,
            "--summary",
            "T1 moved scout west",
            "--confidence",
            "high",
            "--evidence-json",
            '[{"summary":"unit moved"}]',
        ]
    )
    run_record_inference(args)

    args = parse_args(["correct", "--db", str(db_path), "--text", "T1 改为侦察兵探西侧"])
    run_correct(args)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM human_actions").fetchone()
        audits = conn.execute("SELECT COUNT(*) AS n FROM inference_audit").fetchone()

    assert row["summary"] == "T1 改为侦察兵探西侧"
    assert row["confidence"] == "human_corrected"
    assert row["user_correction"] == "T1 改为侦察兵探西侧"
    assert audits["n"] == 2


def test_completed_demo_rejects_default_correction(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )
    try:
        before = {"turn": 1, "overview": {"turn": 1}}
        after = {"turn": 2, "overview": {"turn": 2}}
        before_id = demo.record_state(1, "turn_001_before", before, [])
        after_id = demo.record_state(2, "turn_001_after", after, [])
        demo.record_human_turn(
            turn=1,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            summary="pending",
            rationale="pending",
            tags=[],
            delta=recorder.build_state_delta(before, after),
        )
        demo.complete_session()
    finally:
        demo.close()

    args = parse_args(["correct", "--db", str(db_path), "--text", "late correction"])
    try:
        run_correct(args)
    except recorder.HumanDemoError as exc:
        assert "completed" in str(exc)
    else:
        raise AssertionError("completed demo should reject correction by default")


def test_snapshot_quality_downgrades_missing_critical_capture_fields():
    before = {
        "turn": 1,
        "overview": {"turn": 1, "num_cities": 0, "num_units": 0},
        "cities": [],
        "units": [],
        "research_civic": {},
    }
    after = {
        "turn": 2,
        "overview": {"turn": 2, "num_cities": 1, "num_units": 1},
        "cities": [],
        "units": None,
        "research_civic": {},
    }
    delta = recorder.build_state_delta(before, after)
    rule = recorder.build_rule_inference(
        delta,
        facts=[
            {
                "category": "city",
                "kind": "city_added",
                "summary": "新增城市 西安",
                "importance": "high",
            }
        ],
    )

    adjusted = recorder.apply_snapshot_quality_to_rule(rule, before, after)

    assert adjusted["confidence"] == "medium"
    assert adjusted["needs_review"] is True
    assert "after.cities missing" in adjusted["capture_quality_issues"][0]
    assert "采集缺口需复核" in adjusted["summary"]


def test_tool_timing_summary_reports_failures_and_slowest_tools(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    demo = recorder.SqliteDemoRecorder(
        demo_id="demo_test",
        save_name="test 1",
        db_path=db_path,
    )

    async def run_calls():
        await demo.tool_call("get_ok", {}, _fake_async_result)
        try:
            await demo.tool_call("get_fail", {}, _fake_async_error)
        except RuntimeError:
            pass

    try:
        asyncio.run(run_calls())
        summary = demo.tool_timing_summary(start_seq=0, wall_ms=123)

        assert summary["wall_ms"] == 123
        assert summary["tool_call_count"] == 2
        assert summary["failed_tool_count"] == 1
        assert summary["slowest_tools"]
        assert {row["tool"] for row in summary["slowest_tools"]} == {"get_ok", "get_fail"}
    finally:
        demo.close()


def test_self_play_command_does_not_require_existing_db():
    args = parse_args(["self-play", "--turns", "5"])

    assert args.command == "self-play"
    assert args.turns == 5


def test_watch_command_requires_existing_demo_reference():
    try:
        parse_args(["watch"])
    except SystemExit as exc:
        assert "watch requires --db or --demo-id" in str(exc)
    else:
        raise AssertionError("watch should require --db or --demo-id")


def test_watch_command_parses_safety_options():
    args = parse_args(
        [
            "watch",
            "--demo-id",
            "demo_test",
            "--poll-seconds",
            "1.5",
            "--stable-seconds",
            "2.25",
            "--max-turns",
            "3",
            "--no-stop-on-review",
            "--no-stop-on-periodic-question",
        ]
    )

    assert args.command == "watch"
    assert args.poll_seconds == 1.5
    assert args.stable_seconds == 2.25
    assert args.max_turns == 3
    assert args.stop_on_review is False
    assert args.stop_on_periodic_question is False


def test_watch_transition_status_pauses_on_skipped_turns():
    assert _watch_transition_status(18, 18, pause_on_skip=True) == "waiting"
    assert _watch_transition_status(18, 19, pause_on_skip=True) == "ready"
    assert _watch_transition_status(18, 20, pause_on_skip=False) == "ready"
    try:
        _watch_transition_status(18, 20, pause_on_skip=True)
    except recorder.HumanDemoError as exc:
        assert "turn jump from T18 to T20" in str(exc)
    else:
        raise AssertionError("skipped turns should pause watch by default")


async def _fake_async_error():
    raise RuntimeError("boom")
