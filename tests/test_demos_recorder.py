import asyncio
import sqlite3
import tomllib

from codex_hl.demos import recorder
from codex_hl.demos.cli import parse_args, run_correct, run_record_inference, run_report_only


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
        assert action_count == 1
        assert delta_count == 1
        row = demo.conn.execute("SELECT * FROM human_actions").fetchone()
        assert row["confidence"] == "manual"
        assert row["needs_review"] == 0
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
