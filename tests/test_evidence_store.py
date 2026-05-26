import json
from pathlib import Path

from codex_hl.evidence.store import EpisodeReader, EpisodeStore, rebuild_episode_db


def test_episode_store_round_trips_structured_artifacts_and_save_blob(tmp_path):
    episode = tmp_path / "episodes" / "ep_db"
    store = EpisodeStore(episode, "ep_db", create=True, reset=True)

    header = {"episode_id": "ep_db", "requested_turns": 3}
    store.put_episode_header(header, save_name="test 1", requested_turns=3)
    store.append_jsonl(
        "raw/tool_calls.jsonl",
        {"tool_call_id": "tool-0001", "turn": 1, "tool": "overview", "success": True},
    )
    store.append_jsonl(
        "raw/mcp.jsonl",
        {"call_id": "lua-0001", "context": "overview", "success": True, "request": "print(1)"},
    )
    store.put_json_artifact(
        "raw/civ6_states/state-0001-T0001-turn_start_1.json",
        {"snapshot_id": "state-0001-T0001-turn_start_1", "episode_id": "ep_db", "turn": 1},
        kind="state_snapshot",
    )
    store.append_jsonl(
        "derived/decision_atoms.jsonl",
        {
            "decision_id": "decision-0001",
            "episode_id": "ep_db",
            "turn": 1,
            "selected_action": "wait",
        },
    )
    save_artifact_id = store.put_binary_artifact(
        "raw/saves/save-0001_start.Civ6Save",
        b"fake-save-bytes",
        kind="save_file",
    )
    store.append_jsonl(
        "raw/saves/save_index.jsonl",
        {
            "save_id": "save-0001",
            "episode_id": "ep_db",
            "turn": 1,
            "label": "start",
            "episode_path": str(episode / "raw" / "saves" / "save-0001_start.Civ6Save"),
            "save_artifact_id": save_artifact_id,
        },
    )
    store.put_json_artifact(
        "derived/report_pack.json",
        {"episode_id": "ep_db", "run": {"actual_turns": 3}},
        kind="report_pack",
    )
    store.put_text_artifact(
        "outcome/observation_report.html",
        "<html lang='zh-CN'>ok</html>",
        kind="human_report",
        media_type="text/html",
    )

    reader = EpisodeReader(episode)
    assert reader.backend == "sqlite"
    assert reader.read_json("header.json") == header
    assert reader.read_jsonl("raw/tool_calls.jsonl")[0]["tool_call_id"] == "tool-0001"
    assert reader.read_jsonl("raw/mcp.jsonl")[0]["call_id"] == "lua-0001"
    assert reader.state_rows()[0][1]["snapshot_id"] == "state-0001-T0001-turn_start_1"
    assert reader.read_jsonl("derived/decision_atoms.jsonl")[0]["decision_id"] == "decision-0001"
    assert reader.read_jsonl("raw/saves/save_index.jsonl")[0]["save_artifact_id"] == save_artifact_id

    exported = store.export_legacy_tree()
    exported_save = episode / "raw" / "saves" / "save-0001_start.Civ6Save"
    assert exported_save.read_bytes() == b"fake-save-bytes"
    assert any(path.name == "observation_report.html" for path in exported)


def test_rebuild_episode_db_imports_existing_legacy_tree(tmp_path):
    episode = tmp_path / "episodes" / "old_ep"
    (episode / "raw" / "civ6_states").mkdir(parents=True)
    (episode / "raw" / "saves").mkdir(parents=True)
    (episode / "derived").mkdir(parents=True)
    (episode / "outcome").mkdir(parents=True)
    (episode / "header.json").write_text(json.dumps({"episode_id": "old_ep"}), encoding="utf-8")
    (episode / "raw" / "tool_calls.jsonl").write_text(
        json.dumps({"tool_call_id": "tool-0001", "success": True}) + "\n",
        encoding="utf-8",
    )
    (episode / "raw" / "mcp.jsonl").write_text("", encoding="utf-8")
    (episode / "raw" / "saves" / "save-0001_start.Civ6Save").write_bytes(b"legacy-save")
    (episode / "raw" / "saves" / "save_index.jsonl").write_text(
        json.dumps(
            {
                "save_id": "save-0001",
                "episode_id": "old_ep",
                "episode_path": str(episode / "raw" / "saves" / "save-0001_start.Civ6Save"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (episode / "raw" / "civ6_states" / "state-0001.json").write_text(
        json.dumps({"snapshot_id": "state-0001", "turn": 1}),
        encoding="utf-8",
    )
    (episode / "derived" / "decision_atoms.jsonl").write_text("", encoding="utf-8")
    (episode / "derived" / "report_pack.json").write_text(
        json.dumps({"episode_id": "old_ep"}),
        encoding="utf-8",
    )
    (episode / "outcome" / "observation_report.html").write_text("html", encoding="utf-8")

    store = rebuild_episode_db(episode)
    reader = EpisodeReader(episode)

    assert store.db_path.exists()
    assert reader.read_json("header.json")["episode_id"] == "old_ep"
    assert reader.read_jsonl("raw/tool_calls.jsonl")[0]["tool_call_id"] == "tool-0001"
    assert reader.read_bytes("raw/saves/save-0001_start.Civ6Save") == b"legacy-save"
    assert reader.state_rows()[0][1]["snapshot_id"] == "state-0001"
