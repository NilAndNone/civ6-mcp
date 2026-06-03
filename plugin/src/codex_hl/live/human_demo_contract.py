"""Human Demo T50 reproduction contract v2 evaluation.

This module is read-only over completed episode evidence. It scores final T50
metric acceptance and keeps causal-chain / turn-node alignment as diagnostic
quality evidence. It does not start Civ6, mutate saves, or promote strategy
assets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from codex_hl.evidence.store import EpisodeReader, EpisodeStoreError
from codex_hl.live.ledger import LIVE_EVENTS_LOGICAL_PATH, now_iso
from codex_hl.live.plan_store import LIVE_PLAN_EVENTS_LOGICAL_PATH


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
CONTRACT_VERSION = "human_demo_t50_reproduction_v2"
REFERENCE_DEMO_DB = "human_demos/human_demo_20260527_074225/demo.sqlite"
CRITICAL_STOP_NODES = ("T16-T17", "T25", "T29")

FINAL_TARGETS = {
    "final_turn": 50,
    "num_cities": 4,
    "total_population": 20,
    "science_yield": 20.8,
    "culture_yield": 20.1,
    "era_score": 31,
}

ASSUMPTIONS_AND_STOP_RULES = {
    "coordinate_equivalence": "坐标可因地图/随机事件小幅偏移，但必须解释战略等价性；无解释早二城不算复刻。",
    "stage_floor_acceptance": "阶段性指标大于等于里程碑即可提前通过；提前万神殿、宗教或落城仍必须保留对应因果链证据。",
    "rollback_save_materialization": "通过节点可作为回滚点，但继承通过只接受实际物化的 rollback save；已撤销或重命名的 stale artifact 不得污染验收。",
    "major_bug_restart": "重大 bug 修复后的下一次完整验收应从 test 1 重新开始；仅技术确认才可临时从已通过节点回滚。",
    "stop_after_three": "连续 3 次有效尝试在 T17、T25 或 T29 任一关键节点大幅偏离，应停止运行并写复盘。",
    "no_information_loss": "实现、记录、评估、复盘必须覆盖全部策略要义、阶段里程碑、检查点、失败判据、最终指标和停止规则。",
}

STRATEGY_ESSENTIALS = [
    "开局安全不是防守，是收益化风险。T1 西安先出投石兵，勇士探索，政策保留纪律/君主崇拜，目标是把蛮族转成清营地、时代分、护航和弓箭手升级条件。",
    "建造者不是开局生产核心。demo 的早期建造者来自村庄奖励；它的关键用途是 T13/T16 两次砍树，服务圣地和圣地项目，而不是普通铺田。",
    "宗教移民必须由圣地链触发。占星术 -> 圣地 -> 圣地项目 -> 采矿砍树 -> 买森林再砍 -> T16 宗教移民/免费开拓者；缺任一环都只是表层模仿。",
    "第二城不是越早越好。有效二城是 T25 益阳 `(59,36)`：由免费开拓者链产生，有投石兵护航，受蛮族压力改线，落点同时解决安全、死海时代分和扩张节奏。",
    "第三城承担资源锁定。T25 上海 `(65,37)` 与益阳同回合落地，核心不是“多一城”，而是锁三处马匹，为后续卖马、现金购买、政策切换和发展加速服务。",
    "黄金时代靠来源组合，不靠总分碰运气。关键来源包括玫瑰湖、村庄、清营地、首万神殿、首宗教、益阳死海/沙漠落城、T29 清危机和遇新文明。",
    "宗教服务科文，不是终点。T20 合唱圣歌补文化，朝圣做信仰经济；T31 雄伟壮丽把信仰转建造者/商人/开拓者；T37 后用政策、砍树、交易和学院项目冲 T50 科文。",
    "现金转化是主线。T32 卖 14 马 + 开放边界换 100 金，T37 再卖马支撑付费切殖民，T47 卖棉花买建造者；资源库存要转为即时产能/尤里卡/扩张。",
    "后期科文来自项目和人口。T27 西安神社后转学院，T41 上海学院、南京纪念碑、西安图书馆，T47-T49 上海/西安学院项目把科技推到 20+。",
]

STAGES = [
    {
        "stage_id": "T1-T7",
        "turn_range": [1, 7],
        "milestone": "开局底盘。西安 `(62,41)`；科技占星术，市政法典；生产投石兵；勇士向玫瑰湖探索；T6 时代分 3 -> 4，村庄建造者到位，投石兵开始外移。",
    },
    {
        "stage_id": "T8-T13",
        "turn_range": [8, 13],
        "milestone": "从假扩张切到圣地节奏。西安不要继续 settler/builder rush，T8 转 `DISTRICT_HOLY_SITE`；T9 采矿业；T13 建造者在 `(63,40)` 砍树，圣地完成并转圣地项目。",
    },
    {
        "stage_id": "T14-T17",
        "turn_range": [14, 17],
        "milestone": "宗教移民窗口。T15 继续圣地项目；T16 买森林地块，建造者最后一砍，宗教移民触发免费开拓者，时代分 7 -> 9；T17 买投石兵护航。",
    },
    {
        "stage_id": "T18-T25",
        "turn_range": [18, 25],
        "milestone": "双开拓者落城。免费开拓者和投石兵成队向南；西安继续出第二个开拓者；T25 益阳 `(59,36)`、上海 `(65,37)` 同回合落地，城市数 1 -> 3，时代分 13 -> 17。",
    },
    {
        "stage_id": "T26-T31",
        "turn_range": [26, 31],
        "milestone": "锁黄金并转雄伟壮丽。T26 箭术完成，约 30 金升级投石兵为弓箭手；T29 清益阳危机 +3、遇文明 +1，时代分 17 -> 21；T30 进黄金，T31 选雄伟壮丽并信仰购买民用单位。",
    },
    {
        "stage_id": "T32-T37",
        "turn_range": [32, 37],
        "milestone": "资源变现与第四城准备。T32 卖马/开放边界换 100 金并买建造者；T37 花钱切殖民，双建造者砍树，开拓者立即产出，目标是南京棉花/行业点。",
    },
    {
        "stage_id": "T41-T44",
        "turn_range": [41, 44],
        "milestone": "四城和政体接管。T41 南京 `(68,42)` 建城，4 城成立；T42 首个行业 +3，科文约 12.5/14.9；T44 古典共和，政策转殖民/城市规划/外交联盟/鼓舞，科技约 17.3。",
    },
    {
        "stage_id": "T47-T50",
        "turn_range": [47, 50],
        "milestone": "科文冲刺。卖棉花买建造者，做三矿山链，触发学徒；上海和西安续学院项目；T49/T50 达到 4 城、人口 20、科技 20.8、文化 20.1。",
    },
]

CHECKPOINTS = [
    {
        "node": "T7",
        "stage_id": "T1-T7",
        "turn": 7,
        "must_observe": "投石兵已出，村庄建造者到位，时代分约 4",
        "failure_criteria": "首都仍在 builder/settler 线且无投石兵安全链",
    },
    {
        "node": "T10",
        "stage_id": "T8-T13",
        "turn": 10,
        "must_observe": "圣地在建，采矿在推进，时代分约 7，蛮族有清营/收益计划",
        "failure_criteria": "蛮族只被当阻塞，或继续无因果早扩张",
    },
    {
        "node": "T13",
        "stage_id": "T8-T13",
        "turn": 13,
        "must_observe": "`(63,40)` 砍树，圣地完成/转圣地项目",
        "failure_criteria": "圣地未落、未砍树、或 fallback 到普通生产",
    },
    {
        "node": "T16-T17",
        "stage_id": "T14-T17",
        "turn": 17,
        "critical_stop_node": True,
        "must_observe": "宗教移民、免费开拓者、买森林砍树、买投石兵护航",
        "failure_criteria": "只点宗教移民但无圣地/项目/砍树/护航链",
    },
    {
        "node": "T20",
        "stage_id": "T18-T25",
        "turn": 20,
        "must_observe": "首宗教，合唱圣歌 + 朝圣，时代分约 13",
        "failure_criteria": "发教太晚，或宗教选择无法服务文化/信仰经济",
    },
    {
        "node": "T25",
        "stage_id": "T18-T25",
        "turn": 25,
        "critical_stop_node": True,
        "must_observe": "益阳 `(59,36)`、上海 `(65,37)`，3 城，时代分约 17",
        "failure_criteria": "任意早二城替代益阳逻辑；不能解释来源/护航/资源",
    },
    {
        "node": "T29",
        "stage_id": "T26-T31",
        "turn": 29,
        "critical_stop_node": True,
        "must_observe": "清益阳危机，黄金锁定，时代分约 21",
        "failure_criteria": "T30 仍被蛮族压制，时代分来源不可解释",
    },
    {
        "node": "T31",
        "stage_id": "T26-T31",
        "turn": 31,
        "must_observe": "雄伟壮丽，信仰购买民用单位",
        "failure_criteria": "进黄金但信仰没有转扩张/建设能力",
    },
    {
        "node": "T37",
        "stage_id": "T32-T37",
        "turn": 37,
        "must_observe": "卖资源换钱，付费切殖民，双砍树出开拓者",
        "failure_criteria": "第四城仍靠慢造，资源没有变现",
    },
    {
        "node": "T41",
        "stage_id": "T41-T44",
        "turn": 41,
        "must_observe": "南京 `(68,42)`，4 城，西安/上海接学院线",
        "failure_criteria": "4 城未成，或新增城市不服务棉花/行业/科文",
    },
    {
        "node": "T44",
        "stage_id": "T41-T44",
        "turn": 44,
        "must_observe": "古典共和，科文约 17/16，政策组合支持扩张和产能",
        "failure_criteria": "政体/政策滞后，科文未接上",
    },
    {
        "node": "T50",
        "stage_id": "T47-T50",
        "turn": 50,
        "must_observe": "T50 已达成，4 城、人口约 20、科技 20.8、文化 20.1、时代分 31",
        "failure_criteria": "只满足 T50 或 4 城但科文/时代分低，或科文高但黄金/扩张链断裂",
    },
]


class HumanDemoContractError(RuntimeError):
    """User-facing error for v2 contract evaluation."""


@dataclass(frozen=True)
class EvidenceBundle:
    episode_id: str
    header: dict[str, Any]
    plan_events: list[dict[str, Any]]
    live_events: list[dict[str, Any]]
    contexts: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    reader_backend: str
    inherited_checkpoint_turn: int = 0
    inherited_checkpoint_sources: list[dict[str, Any]] | None = None


def json_dumps(data: Any, *, indent: int | None = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _clean_number(value: Any) -> Any:
    number = _number(value)
    if isinstance(number, float) and number.is_integer():
        return int(number)
    return number


def _row_text(row: Any) -> str:
    return json_dumps(row, indent=None).upper()


def _xy(row: dict[str, Any]) -> tuple[int, int] | None:
    try:
        return int(row["x"]), int(row["y"])
    except (KeyError, TypeError, ValueError):
        location = row.get("location")
        if isinstance(location, dict):
            try:
                return int(location["x"]), int(location["y"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _rough_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _extract_contexts(plan_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for index, row in enumerate(plan_events):
        if row.get("event_type") != "TURN_CONTEXT_RECORDED":
            continue
        context = _safe_dict(_safe_dict(row.get("payload")).get("context"))
        if not context:
            continue
        contexts.append({"_event_index": index, **context})
    return sorted(contexts, key=lambda item: (int(_number(item.get("turn")) or 0), int(item.get("_event_index") or 0)))


def _extract_actions(live_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        row
        for row in live_events
        if row.get("event_type") in {"ACTION_FINISHED", "ACTION_FAILED", "ACTION_REJECTED"}
    ]
    return sorted(rows, key=lambda row: (int(_number(row.get("turn")) or 0), int(_number(row.get("seq")) or 0)))


def _checkpoint_node_turns() -> dict[str, int]:
    return {str(row["node"]): int(row["turn"]) for row in CHECKPOINTS}


def _checkpoint_token(node: str) -> str:
    return node.upper().replace("-", "_")


def _checkpoint_turn_from_node(node: str) -> int:
    return _checkpoint_node_turns().get(node) or _checkpoint_node_turns().get(node.upper().replace("_", "-")) or 0


def _checkpoint_turns_from_text(text: str, *, source: str) -> list[dict[str, Any]]:
    normalized = str(text or "").upper().replace("-", "_")
    rows: list[dict[str, Any]] = []
    for node, turn in _checkpoint_node_turns().items():
        token = _checkpoint_token(node)
        if re.search(rf"(?:^|_){re.escape(token)}_PASS(?:$|[_.])", normalized):
            rows.append({"node": node, "turn": turn, "source": source, "text": text})
    return rows


def _episode_file_exists(reader: EpisodeReader, logical_path: str) -> bool:
    try:
        return (reader.episode_root / Path(logical_path)).exists()
    except (OSError, EpisodeStoreError, ValueError):
        return False


def _inherited_checkpoint_sources(reader: EpisodeReader, header: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for key in ("save_name", "recovery_save_name", "source_save", "rollback_save_name"):
        value = header.get(key)
        if value:
            sources.extend(_checkpoint_turns_from_text(str(value), source=f"header.{key}"))

    store = getattr(reader, "store", None)
    if store is not None:
        for artifact in store.artifacts(prefix="raw/saves/"):
            if not _episode_file_exists(reader, artifact.logical_path):
                continue
            metadata = _safe_dict(getattr(artifact, "metadata", None))
            node = str(metadata.get("checkpoint_node") or "")
            turn = _checkpoint_turn_from_node(node)
            if node and turn:
                sources.append(
                    {
                        "node": node,
                        "turn": turn,
                        "source": "episode_save_metadata",
                        "text": artifact.logical_path,
                    }
                )
            sources.extend(_checkpoint_turns_from_text(artifact.logical_path, source="episode_save_path"))
    else:
        save_dir = reader.episode_root / "raw" / "saves"
        if save_dir.exists():
            for path in save_dir.glob("*.Civ6Save"):
                sources.extend(_checkpoint_turns_from_text(path.name, source="episode_save_path"))
    return sources


def _read_optional_json(reader: EpisodeReader, logical_path: str) -> dict[str, Any]:
    try:
        return reader.read_json(logical_path)
    except (FileNotFoundError, EpisodeStoreError, json.JSONDecodeError):
        return {}


def _read_optional_jsonl(reader: EpisodeReader, logical_path: str) -> list[dict[str, Any]]:
    try:
        return reader.read_jsonl(logical_path)
    except (FileNotFoundError, EpisodeStoreError, json.JSONDecodeError):
        return []


def read_episode_evidence(episode_id: str, *, workspace: Path = WORKSPACE_ROOT) -> EvidenceBundle:
    episode_root = workspace.resolve() / "episodes" / episode_id
    if not episode_root.exists():
        raise HumanDemoContractError(f"episode not found: {episode_root}")
    reader = EpisodeReader(episode_root)
    header = _read_optional_json(reader, "header.json")
    plan_events = _read_optional_jsonl(reader, LIVE_PLAN_EVENTS_LOGICAL_PATH)
    live_events = _read_optional_jsonl(reader, LIVE_EVENTS_LOGICAL_PATH)
    contexts = _extract_contexts(plan_events)
    actions = _extract_actions(live_events)
    inherited_sources = _inherited_checkpoint_sources(reader, header)
    inherited_turn = max([int(source.get("turn") or 0) for source in inherited_sources] or [0])
    return EvidenceBundle(
        episode_id=episode_id,
        header=header,
        plan_events=plan_events,
        live_events=live_events,
        contexts=contexts,
        actions=actions,
        reader_backend=reader.backend,
        inherited_checkpoint_turn=inherited_turn,
        inherited_checkpoint_sources=inherited_sources,
    )


def _context_at(contexts: list[dict[str, Any]], turn: int) -> dict[str, Any]:
    candidates = [row for row in contexts if int(_number(row.get("turn")) or 0) <= turn]
    return candidates[-1] if candidates else (contexts[0] if contexts else {})


def _latest_context(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    return contexts[-1] if contexts else {}


def _overview(context: dict[str, Any]) -> dict[str, Any]:
    return _safe_dict(context.get("overview"))


def _city_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _safe_list(context.get("cities")) if isinstance(row, dict)]


def _unit_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _safe_list(context.get("units")) if isinstance(row, dict)]


def _city_count(context: dict[str, Any]) -> int:
    value = _number(_overview(context).get("num_cities"))
    if isinstance(value, (int, float)):
        return int(value)
    return len(_city_rows(context))


def _unit_count(context: dict[str, Any], unit_type: str) -> int:
    wanted = unit_type.upper()
    return len(
        [
            unit
            for unit in _unit_rows(context)
            if str(unit.get("unit_type") or unit.get("type") or "").upper() == wanted
        ]
    )


def _era_score(context: dict[str, Any]) -> int | None:
    value = _number(_overview(context).get("era_score"))
    return int(value) if isinstance(value, (int, float)) else None


def _metric(context: dict[str, Any], key: str) -> float | int | None:
    return _number(_overview(context).get(key))


def _actions_to(actions: list[dict[str, Any]], turn: int) -> list[dict[str, Any]]:
    return [row for row in actions if int(_number(row.get("turn")) or 0) <= turn]


def _passing_actions(actions: list[dict[str, Any]], turn: int) -> list[dict[str, Any]]:
    return [
        row
        for row in _actions_to(actions, turn)
        if row.get("event_type") == "ACTION_FINISHED" and row.get("verifier_status") == "PASS"
    ]


def _action_has(
    actions: list[dict[str, Any]],
    turn: int,
    *,
    tool: str | None = None,
    text: str | None = None,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[bool, str | None]:
    wanted_text = text.upper() if text else None
    for row in _passing_actions(actions, turn):
        if tool is not None and row.get("tool") != tool:
            continue
        if wanted_text is not None and wanted_text not in _row_text(row):
            continue
        if predicate is not None and not predicate(row):
            continue
        return True, _action_evidence(row)
    return False, None


def _matching_actions(
    actions: list[dict[str, Any]],
    turn: int,
    *,
    since_turn: int | None = None,
    tool: str | None = None,
    text: str | None = None,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    wanted_text = text.upper() if text else None
    rows = []
    for row in _passing_actions(actions, turn):
        row_turn = int(_number(row.get("turn")) or 0)
        if since_turn is not None and row_turn < since_turn:
            continue
        if tool is not None and row.get("tool") != tool:
            continue
        if wanted_text is not None and wanted_text not in _row_text(row):
            continue
        if predicate is not None and not predicate(row):
            continue
        rows.append(row)
    return rows


def _action_has_between(
    actions: list[dict[str, Any]],
    start_turn: int,
    end_turn: int,
    *,
    tool: str | None = None,
    text: str | None = None,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[bool, str | None]:
    rows = _matching_actions(
        actions,
        end_turn,
        since_turn=start_turn,
        tool=tool,
        text=text,
        predicate=predicate,
    )
    return (True, _action_evidence(rows[0])) if rows else (False, None)


def _action_text_has_coord(row: dict[str, Any], coord: tuple[int, int]) -> bool:
    x, y = coord
    args = _safe_dict(row.get("args"))
    if int(_number(args.get("x")) or -9999) == x and int(_number(args.get("y")) or -9999) == y:
        return True
    if int(_number(args.get("target_x")) or -9999) == x and int(_number(args.get("target_y")) or -9999) == y:
        return True
    text = _row_text(row).replace(" ", "")
    return f"{x},{y}" in text or f"({x},{y})" in text or (f'"X":{x}' in text and f'"Y":{y}' in text)


def _chop_actions(
    actions: list[dict[str, Any]],
    turn: int,
    *,
    since_turn: int | None = None,
) -> list[dict[str, Any]]:
    return _matching_actions(actions, turn, since_turn=since_turn, tool="unit_action", text="REMOVE_FEATURE")


def _chop_evidence(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return "; ".join(_action_evidence(row) for row in rows[:3])


def _action_evidence(row: dict[str, Any]) -> str:
    args = _safe_dict(row.get("args"))
    payload = _safe_dict(row.get("payload"))
    result = payload.get("result")
    detail = result if isinstance(result, str) and result else json_dumps(args, indent=None)
    if len(detail) > 140:
        detail = detail[:137] + "..."
    return f"T{row.get('turn')} {row.get('tool')} {detail}"


def _city_near(context: dict[str, Any], target: tuple[int, int], *, tolerance: int = 1) -> tuple[bool, str | None]:
    for city in _city_rows(context):
        pos = _xy(city)
        if pos is None:
            continue
        if _rough_distance(pos, target) <= tolerance:
            return True, f"T{context.get('turn')} city {city.get('name') or city.get('city_id')} at {pos}"
    return False, None


def _current_build_or_action(
    context: dict[str, Any],
    actions: list[dict[str, Any]],
    turn: int,
    item_name: str,
) -> tuple[bool, str | None]:
    item = item_name.upper()
    for city in _city_rows(context):
        current = str(city.get("currently_building") or "").upper()
        districts = _row_text(city.get("districts"))
        buildings = _row_text(city.get("buildings"))
        if item in current or item in districts or item in buildings:
            return True, f"T{context.get('turn')} city {city.get('name') or city.get('city_id')} has/builds {item_name}"
    return _action_has(actions, turn, tool="set_city_production", text=item)


def _policy_action(actions: list[dict[str, Any]], turn: int, policy: str) -> tuple[bool, str | None]:
    return _action_has(actions, turn, tool="set_policies", text=policy)


def _religion_belief_action(
    actions: list[dict[str, Any]],
    turn: int,
    belief: str,
    *,
    since_turn: int | None = None,
) -> tuple[bool, str | None]:
    if since_turn is not None:
        return _action_has_between(actions, since_turn, turn, tool="found_religion", text=belief)
    return _action_has(actions, turn, tool="found_religion", text=belief)


def _golden_locked(context: dict[str, Any], *, target_score: int) -> tuple[bool, str | None]:
    overview = _overview(context)
    era_score = _number(overview.get("era_score"))
    golden_threshold = _number(overview.get("era_golden_threshold"))
    if isinstance(era_score, (int, float)) and era_score >= target_score:
        return True, f"T{context.get('turn')} era_score={_clean_number(era_score)}"
    if isinstance(era_score, (int, float)) and isinstance(golden_threshold, (int, float)) and era_score >= golden_threshold:
        return True, f"T{context.get('turn')} era_score={_clean_number(era_score)} threshold={_clean_number(golden_threshold)}"
    return False, None


def _observation(obs_id: str, label: str, observed: bool, evidence: str | None = None) -> dict[str, Any]:
    return {
        "id": obs_id,
        "label": label,
        "observed": bool(observed),
        "evidence": evidence,
    }


def _score_observations(observations: list[dict[str, Any]]) -> tuple[float, str]:
    if not observations:
        return 0.0, "missing"
    passed = len([row for row in observations if row.get("observed") is True])
    score = passed / len(observations)
    if passed == len(observations):
        return score, "pass"
    if passed:
        return score, "partial"
    return score, "fail"


def _eval_checkpoint_for_context(
    checkpoint: dict[str, Any],
    bundle: EvidenceBundle,
    context: dict[str, Any],
) -> dict[str, Any]:
    deadline_turn = int(checkpoint["turn"])
    context_turn = int(_number(context.get("turn") or _overview(context).get("turn")) or 0)
    turn = context_turn if 0 < context_turn <= deadline_turn else deadline_turn
    actions = bundle.actions
    observations: list[dict[str, Any]] = []

    if checkpoint["node"] == "T7":
        has_slinger_prod, ev1 = _current_build_or_action(context, actions, turn, "UNIT_SLINGER")
        observations.append(_observation("slinger_opening", "T1-T7 投石兵安全链已启动", has_slinger_prod or _unit_count(context, "UNIT_SLINGER") > 0, ev1))
        observations.append(_observation("village_builder", "村庄建造者到位而非首都 builder rush", _unit_count(context, "UNIT_BUILDER") > 0, f"T{context.get('turn')} builders={_unit_count(context, 'UNIT_BUILDER')}"))
        era = _era_score(context)
        observations.append(_observation("era_score_around_4", "时代分约 4", era is not None and era >= 4, f"T{context.get('turn')} era_score={era}"))
        bad_prod = any(
            str(city.get("currently_building") or "").upper() in {"UNIT_BUILDER", "UNIT_SETTLER"}
            for city in _city_rows(context)
        )
        warrior_north = any(
            str(unit.get("unit_type") or "").upper() == "UNIT_WARRIOR"
            and _number(unit.get("y")) is not None
            and float(_number(unit.get("y")) or 999) <= 40
            for unit in _unit_rows(context)
        )
        warrior_move, ev4 = _action_has_between(
            actions,
            1,
            turn,
            tool="unit_action",
            predicate=lambda row: str(_safe_dict(row.get("args")).get("action") or "").lower() == "move"
            and float(_number(_safe_dict(row.get("args")).get("target_y")) or 999) <= 40,
        )
        observations.append(_observation("not_builder_settler_line", "首都没有停留在 builder/settler 线", not bad_prod, f"T{context.get('turn')} production={_safe_list(context.get('production', {}).get('cities'))}"))
        observations.append(_observation("warrior_exploration", "勇士向玫瑰湖/北部收益探索", warrior_north or warrior_move, ev4 or f"T{context.get('turn')} warrior_north={warrior_north}"))
    elif checkpoint["node"] == "T10":
        holy, ev1 = _current_build_or_action(context, actions, turn, "DISTRICT_HOLY_SITE")
        mining, ev2 = _action_has(actions, turn, tool="set_research", text="TECH_MINING")
        era = _era_score(context)
        slinger_chain = _unit_count(context, "UNIT_SLINGER") > 0 or _action_has(actions, turn, text="UNIT_SLINGER")[0]
        threat_or_camp = bool(_safe_list(context.get("threats"))) or _action_has(actions, turn, tool="unit_action", text="ATTACK")[0]
        observations.extend(
            [
                _observation("holy_site_in_progress", "圣地在建", holy, ev1),
                _observation("mining_in_progress", "采矿在推进", mining, ev2),
                _observation("era_score_around_7", "时代分约 7", era is not None and era >= 7, f"T{context.get('turn')} era_score={era}"),
                _observation("barbarian_value_plan", "蛮族被纳入清营/收益计划", slinger_chain and threat_or_camp, f"T{context.get('turn')} threats={len(_safe_list(context.get('threats')))} slingers={_unit_count(context, 'UNIT_SLINGER')}"),
            ]
        )
    elif checkpoint["node"] == "T13":
        chop_rows = _chop_actions(actions, turn)
        chop = any(_action_text_has_coord(row, (63, 40)) for row in chop_rows)
        ev1 = _chop_evidence([row for row in chop_rows if _action_text_has_coord(row, (63, 40))])
        holy, ev2 = _current_build_or_action(context, actions, turn, "DISTRICT_HOLY_SITE")
        project, ev3 = _current_build_or_action(context, actions, turn, "PROJECT_ENHANCE_DISTRICT_HOLY_SITE")
        observations.extend(
            [
                _observation("forest_chop_63_40", "`(63,40)` 砍树", chop, ev1),
                _observation("holy_site_completed_or_building", "圣地完成或仍在可验证推进", holy, ev2),
                _observation("holy_site_project_started", "转圣地项目", project, ev3),
            ]
        )
    elif checkpoint["node"] == "T16-T17":
        pantheon, ev1 = _action_has_between(
            actions,
            14,
            turn,
            tool="choose_pantheon",
            text="BELIEF_RELIGIOUS_SETTLEMENTS",
        )
        free_settler = _unit_count(context, "UNIT_SETTLER") > 0 and _city_count(context) <= 1
        buy_tile, ev2 = _action_has(actions, turn, tool="purchase_tile")
        chop_rows = _chop_actions(actions, turn)
        second_chop_rows = _chop_actions(actions, turn, since_turn=14)
        chop = len(chop_rows) >= 2 or bool(second_chop_rows)
        ev3 = _chop_evidence(second_chop_rows or chop_rows)
        buy_slinger, ev4 = _action_has(actions, turn, tool="purchase_item", text="UNIT_SLINGER")
        project, ev5 = _current_build_or_action(context, actions, turn, "PROJECT_ENHANCE_DISTRICT_HOLY_SITE")
        observations.extend(
            [
                _observation("religious_settlements", "宗教移民万神殿", pantheon, ev1),
                _observation("free_settler_present", "免费开拓者出现", free_settler, f"T{context.get('turn')} settlers={_unit_count(context, 'UNIT_SETTLER')} cities={_city_count(context)}"),
                _observation("forest_tile_bought", "买森林地块", buy_tile, ev2),
                _observation("second_chop", "买森林后继续砍树", chop, ev3),
                _observation("slinger_escort_bought", "买投石兵护航", buy_slinger or _unit_count(context, "UNIT_SLINGER") > 0, ev4 or f"T{context.get('turn')} slingers={_unit_count(context, 'UNIT_SLINGER')}"),
                _observation("holy_project_chain", "圣地项目链存在", project, ev5),
            ]
        )
    elif checkpoint["node"] == "T20":
        founded, ev1 = _action_has_between(actions, 18, turn, tool="found_religion")
        choral, ev2 = _religion_belief_action(actions, turn, "BELIEF_CHORAL_MUSIC", since_turn=18)
        pilgrimage, ev3 = _religion_belief_action(actions, turn, "BELIEF_PILGRIMAGE", since_turn=18)
        era = _era_score(context)
        observations.extend(
            [
                _observation("first_religion", "首宗教已建立", founded, ev1),
                _observation("choral_music", "合唱圣歌服务文化", choral, ev2),
                _observation("pilgrimage", "朝圣服务信仰经济", pilgrimage, ev3),
                _observation("era_score_around_13", "时代分约 13", era is not None and era >= 13, f"T{context.get('turn')} era_score={era}"),
            ]
        )
    elif checkpoint["node"] == "T25":
        yiyang, ev1 = _city_near(context, (59, 36), tolerance=0)
        shanghai, ev2 = _city_near(context, (65, 37), tolerance=0)
        era = _era_score(context)
        horse_lock = "HORSES" in _row_text(_safe_dict(context.get("resources")))
        observations.extend(
            [
                _observation("three_cities", "T25 三城", _city_count(context) >= 3, f"T{context.get('turn')} cities={_city_count(context)}"),
                _observation("yiyang_equivalent", "益阳 `(59,36)` 或有解释的战略等价落点", yiyang, ev1),
                _observation("shanghai_horse_lock", "上海 `(65,37)` 锁马匹资源", shanghai and horse_lock, ev2 or f"T{context.get('turn')} resources={_safe_dict(context.get('resources')).get('nearby')}"),
                _observation("era_score_around_17", "时代分约 17", era is not None and era >= 17, f"T{context.get('turn')} era_score={era}"),
                _observation("settler_escort_chain", "有投石兵护航链", _unit_count(context, "UNIT_SLINGER") > 0 or _unit_count(context, "UNIT_ARCHER") > 0, f"T{context.get('turn')} slingers={_unit_count(context, 'UNIT_SLINGER')} archers={_unit_count(context, 'UNIT_ARCHER')}"),
            ]
        )
    elif checkpoint["node"] == "T29":
        golden, ev1 = _golden_locked(context, target_score=21)
        threats = len(_safe_list(context.get("threats")))
        attack, ev2 = _action_has(actions, turn, tool="unit_action", text="ATTACK")
        upgraded, ev3 = _action_has(actions, turn, tool="upgrade_unit", text="UNIT_ARCHER")
        archer_chain = upgraded or _unit_count(context, "UNIT_ARCHER") > 0
        observations.extend(
            [
                _observation("golden_locked", "黄金锁定", golden, ev1),
                _observation("barbarian_crisis_cleared", "清益阳危机/清营收益有动作", threats <= 1 and attack, ev2 or f"T{context.get('turn')} threats={threats}"),
                _observation("era_sources_auditable", "时代分来源可解释", _era_score(context) is not None and bool(bundle.contexts), f"T{context.get('turn')} era_score={_era_score(context)}"),
                _observation("archer_upgrade_chain", "T26 箭术后投石兵升级为弓箭手", archer_chain, ev3 or f"T{context.get('turn')} archers={_unit_count(context, 'UNIT_ARCHER')}"),
            ]
        )
    elif checkpoint["node"] == "T31":
        mon = False
        ev1 = None
        for marker in (
            "COMMEMORATION_INFRASTRUCTURE",
            "COMMEMORATION_MONUMENTALITY",
            "MONUMENTALITY",
        ):
            mon, ev1 = _action_has(actions, turn, tool="choose_dedication", text=marker)
            if mon:
                break
        faith_purchase, ev2 = _action_has(actions, turn, tool="purchase_item", text="YIELD_FAITH")
        observations.extend(
            [
                _observation("monumentality", "雄伟壮丽", mon, ev1),
                _observation("faith_to_civilian_units", "信仰购买民用单位", faith_purchase, ev2),
            ]
        )
    elif checkpoint["node"] == "T37":
        trade, ev1 = _action_has(actions, turn, tool="propose_trade")
        colonization, ev2 = _policy_action(actions, turn, "POLICY_COLONIZATION")
        chop_rows = _chop_actions(actions, turn, since_turn=32)
        chop = len(chop_rows) >= 2
        ev3 = _chop_evidence(chop_rows)
        settler_prod, ev4 = _current_build_or_action(context, actions, turn, "UNIT_SETTLER")
        observations.extend(
            [
                _observation("resources_monetized", "资源/开放边界变现", trade, ev1),
                _observation("paid_colonization_switch", "付费切殖民政策", colonization, ev2),
                _observation("double_chop", "双建造者砍树", chop, ev3),
                _observation("settler_ready_for_fourth_city", "开拓者立即产出/准备第四城", settler_prod or _unit_count(context, "UNIT_SETTLER") > 0, ev4 or f"T{context.get('turn')} settlers={_unit_count(context, 'UNIT_SETTLER')}"),
            ]
        )
    elif checkpoint["node"] == "T41":
        nanjing, ev1 = _city_near(context, (68, 42), tolerance=1)
        campus = "DISTRICT_CAMPUS" in _row_text(_city_rows(context))
        observations.extend(
            [
                _observation("four_cities", "4 城成立", _city_count(context) >= 4, f"T{context.get('turn')} cities={_city_count(context)}"),
                _observation("nanjing_cotton_industry_site", "南京 `(68,42)` 服务棉花/行业点", nanjing, ev1),
                _observation("campus_line", "西安/上海接学院线", campus or _current_build_or_action(context, actions, turn, "DISTRICT_CAMPUS")[0], f"T{context.get('turn')} cities={_city_rows(context)}"),
            ]
        )
    elif checkpoint["node"] == "T44":
        gov, ev1 = _action_has(actions, turn, tool="change_government", text="GOVERNMENT_CLASSICAL_REPUBLIC")
        pol_ok = any(_policy_action(actions, turn, policy)[0] for policy in ("POLICY_COLONIZATION", "POLICY_URBAN_PLANNING", "POLICY_DIPLOMATIC_LEAGUE", "POLICY_INSPIRATION"))
        sci = _metric(context, "science_yield")
        cul = _metric(context, "culture_yield")
        observations.extend(
            [
                _observation("classical_republic", "古典共和", gov, ev1),
                _observation("policy_combo", "政策组合支持扩张和产能", pol_ok, "policy actions recorded" if pol_ok else None),
                _observation("science_around_17", "科技约 17", isinstance(sci, (int, float)) and sci >= 16, f"T{context.get('turn')} science={sci}"),
                _observation("culture_around_16", "文化约 16", isinstance(cul, (int, float)) and cul >= 15, f"T{context.get('turn')} culture={cul}"),
            ]
        )
    elif checkpoint["node"] == "T50":
        sci = _metric(context, "science_yield")
        cul = _metric(context, "culture_yield")
        pop = _metric(context, "total_population")
        observations.extend(
            [
                _observation("four_cities_final", "T50 4 城", _city_count(context) >= 4, f"T{context.get('turn')} cities={_city_count(context)}"),
                _observation("population_20", "总人口约 20", isinstance(pop, (int, float)) and pop >= 20, f"T{context.get('turn')} population={pop}"),
                _observation("science_20_8", "科技 20.8", isinstance(sci, (int, float)) and sci >= 20.8, f"T{context.get('turn')} science={sci}"),
                _observation("culture_20_1", "文化 20.1", isinstance(cul, (int, float)) and cul >= 20.1, f"T{context.get('turn')} culture={cul}"),
                _observation("golden_chain_intact", "黄金/扩张链不断裂", _era_score(context) is not None and _era_score(context) >= 31, f"T{context.get('turn')} era_score={_era_score(context)}"),
            ]
        )

    score, status = _score_observations(observations)
    critical = bool(checkpoint.get("critical_stop_node"))
    latest = _latest_context(bundle.contexts)
    final_turn = int(_number(latest.get("turn") or _overview(latest).get("turn")) or 0)
    early_satisfied = status == "pass" and 0 < context_turn <= deadline_turn
    reached = final_turn >= deadline_turn or early_satisfied
    return {
        "node": checkpoint["node"],
        "stage_id": checkpoint["stage_id"],
        "turn": deadline_turn,
        "deadline_turn": deadline_turn,
        "context_turn": context_turn,
        "achieved_turn": context_turn if status == "pass" else None,
        "acceptance_rule": "by_turn_or_early_pass",
        "must_observe": checkpoint["must_observe"],
        "failure_criteria": checkpoint["failure_criteria"],
        "observations": observations,
        "score": round(score, 3),
        "status": status,
        "reached": reached,
        "critical_stop_node": critical,
        "critical_deviation": critical and reached and score < 0.5,
    }


def _checkpoint_candidate_contexts(
    contexts: list[dict[str, Any]],
    turn: int,
) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in contexts
        if 0 < int(_number(row.get("turn") or _overview(row).get("turn")) or 0) <= turn
    ]
    if candidates:
        return candidates
    fallback = _context_at(contexts, turn)
    return [fallback] if fallback else [{}]


def _inherited_checkpoint_result(
    checkpoint: dict[str, Any],
    bundle: EvidenceBundle,
) -> dict[str, Any] | None:
    deadline_turn = int(checkpoint["turn"])
    if deadline_turn <= 0 or deadline_turn > int(bundle.inherited_checkpoint_turn or 0):
        return None
    if any(0 < int(_number(action.get("turn")) or 0) <= deadline_turn for action in bundle.actions):
        return None
    node = str(checkpoint["node"])
    sources = [
        source
        for source in (bundle.inherited_checkpoint_sources or [])
        if int(source.get("turn") or 0) >= deadline_turn
    ]
    evidence = "; ".join(
        f"{source.get('source')}={source.get('text')}"
        for source in sources[:3]
        if source.get("source") or source.get("text")
    )
    observation = _observation(
        "rollback_checkpoint_inherited",
        f"{node} inherited from a passed rollback checkpoint save",
        True,
        evidence or f"inherited_checkpoint_turn={bundle.inherited_checkpoint_turn}",
    )
    return {
        "node": node,
        "stage_id": checkpoint["stage_id"],
        "turn": deadline_turn,
        "deadline_turn": deadline_turn,
        "context_turn": None,
        "achieved_turn": deadline_turn,
        "acceptance_rule": "rollback_checkpoint_inherited",
        "must_observe": checkpoint["must_observe"],
        "failure_criteria": checkpoint["failure_criteria"],
        "observations": [observation],
        "score": 1.0,
        "status": "pass",
        "reached": True,
        "critical_stop_node": bool(checkpoint.get("critical_stop_node")),
        "critical_deviation": False,
        "inherited_from_rollback": True,
        "inherited_checkpoint_turn": int(bundle.inherited_checkpoint_turn or 0),
        "inherited_sources": sources[:5],
        "selected_context_turn": None,
        "evaluated_context_turns": [
            int(_number(context.get("turn") or _overview(context).get("turn")) or 0)
            for context in _checkpoint_candidate_contexts(bundle.contexts, deadline_turn)
        ],
    }


def _eval_checkpoint(
    checkpoint: dict[str, Any],
    bundle: EvidenceBundle,
) -> dict[str, Any]:
    inherited = _inherited_checkpoint_result(checkpoint, bundle)
    if inherited is not None:
        return inherited
    turn = int(checkpoint["turn"])
    evaluated = [
        _eval_checkpoint_for_context(checkpoint, bundle, context)
        for context in _checkpoint_candidate_contexts(bundle.contexts, turn)
    ]
    passes = [row for row in evaluated if row.get("status") == "pass"]
    if passes:
        selected = min(
            passes,
            key=lambda row: int(_number(row.get("achieved_turn")) or turn),
        )
    else:
        selected = max(
            evaluated,
            key=lambda row: (
                float(row.get("score") or 0.0),
                int(_number(row.get("context_turn")) or 0),
            ),
        )
    selected = dict(selected)
    selected["selected_context_turn"] = selected.get("context_turn")
    selected["evaluated_context_turns"] = [
        int(_number(context.get("turn") or _overview(context).get("turn")) or 0)
        for context in _checkpoint_candidate_contexts(bundle.contexts, turn)
    ]
    return selected


def _stage_scores(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for checkpoint in checkpoints:
        by_stage.setdefault(str(checkpoint["stage_id"]), []).append(checkpoint)
    rows: list[dict[str, Any]] = []
    for stage in STAGES:
        stage_id = str(stage["stage_id"])
        items = by_stage.get(stage_id, [])
        score = sum(float(item.get("score") or 0) for item in items) / len(items) if items else 0.0
        rows.append(
            {
                **stage,
                "checkpoint_count": len(items),
                "score": round(score, 3),
                "status": "pass" if items and all(item["status"] == "pass" for item in items) else ("partial" if score > 0 else "fail"),
            }
        )
    return rows


def _final_metrics(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_turn": _clean_number(context.get("turn") or _overview(context).get("turn")),
        "num_cities": _city_count(context),
        "total_population": _clean_number(_overview(context).get("total_population")),
        "science_yield": _clean_number(_overview(context).get("science_yield")),
        "culture_yield": _clean_number(_overview(context).get("culture_yield")),
        "era_score": _clean_number(_overview(context).get("era_score")),
    }


def _target_results(metrics: dict[str, Any]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for key, target in FINAL_TARGETS.items():
        value = _number(metrics.get(key))
        results[key] = isinstance(value, (int, float)) and value >= target
    return results


def evaluate_episode_contract(
    episode_id: str,
    *,
    workspace: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    bundle = read_episode_evidence(episode_id, workspace=workspace)
    checkpoints = [_eval_checkpoint(checkpoint, bundle) for checkpoint in CHECKPOINTS]
    stages = _stage_scores(checkpoints)
    latest = _latest_context(bundle.contexts)
    metrics = _final_metrics(latest)
    target_results = _target_results(metrics)
    critical_deviations = [
        checkpoint["node"]
        for checkpoint in checkpoints
        if checkpoint.get("critical_deviation") is True
    ]
    valid_strategy_attempt = bool(bundle.contexts) and int(_number(metrics.get("final_turn")) or 0) >= 7
    metrics_success = all(target_results.values())
    causal_chain_complete = all(checkpoint["status"] == "pass" for checkpoint in checkpoints)
    success = valid_strategy_attempt and metrics_success
    return {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_iso(),
        "workspace": str(workspace.resolve()),
        "episode_id": episode_id,
        "reference_demo_db": REFERENCE_DEMO_DB,
        "attempt": {
            "valid_strategy_attempt": valid_strategy_attempt,
            "success": success,
            "metrics_success": metrics_success,
            "causal_chain_complete": causal_chain_complete,
            "success_basis": "final_metrics_gte_reference_targets" if success else None,
            "critical_deviations": critical_deviations,
            "not_success_reason": None
            if success
                else "Human Demo T50 v2 metric acceptance requires a valid attempt plus final turn 50 / 4 cities / population 20 / science 20.8 / culture 20.1 / era score 31.",
        },
        "strategy_essentials": STRATEGY_ESSENTIALS,
        "assumptions_and_stop_rules": ASSUMPTIONS_AND_STOP_RULES,
        "stage_scores": stages,
        "checkpoints": checkpoints,
        "final_targets": FINAL_TARGETS,
        "final_metrics": metrics,
        "final_target_results": target_results,
        "evidence": {
            "storage_backend": bundle.reader_backend,
            "live_plan_events_path": LIVE_PLAN_EVENTS_LOGICAL_PATH,
            "live_events_path": LIVE_EVENTS_LOGICAL_PATH,
            "turn_context_count": len(bundle.contexts),
            "action_count": len(bundle.actions),
            "header": bundle.header,
            "inherited_checkpoint_turn": bundle.inherited_checkpoint_turn,
            "inherited_checkpoint_sources": bundle.inherited_checkpoint_sources or [],
        },
    }


def evaluate_attempt_window(
    episode_ids: list[str],
    *,
    workspace: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    attempts = [evaluate_episode_contract(episode_id, workspace=workspace) for episode_id in episode_ids]
    valid_attempts = [row for row in attempts if _safe_dict(row.get("attempt")).get("valid_strategy_attempt") is True]
    latest_three = valid_attempts[-3:]
    repeated: list[str] = []
    if len(latest_three) == 3:
        for node in CRITICAL_STOP_NODES:
            if all(node in _safe_dict(row.get("attempt")).get("critical_deviations", []) for row in latest_three):
                repeated.append(node)
    return {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_iso(),
        "workspace": str(workspace.resolve()),
        "episode_ids": episode_ids,
        "reference_demo_db": REFERENCE_DEMO_DB,
        "strategy_essentials": STRATEGY_ESSENTIALS,
        "assumptions_and_stop_rules": ASSUMPTIONS_AND_STOP_RULES,
        "final_targets": FINAL_TARGETS,
        "attempts": attempts,
        "valid_attempt_count": len(valid_attempts),
        "stop_rule": {
            "critical_nodes": list(CRITICAL_STOP_NODES),
            "window_size": 3,
            "repeated_critical_deviations": repeated,
            "stop_recommended": bool(repeated),
            "required_action": "停止继续搜索并写复盘" if repeated else "可继续，但仍必须逐次按 v2 合同评分",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    if "attempts" in report:
        return _render_window_markdown(report)
    attempt = _safe_dict(report.get("attempt"))
    lines = [
        f"# Human Demo T50 Contract v2: {report.get('episode_id')}",
        "",
        f"- Success: `{str(attempt.get('success')).lower()}`",
        f"- Valid strategy attempt: `{str(attempt.get('valid_strategy_attempt')).lower()}`",
        f"- Final metric success: `{str(attempt.get('metrics_success')).lower()}`",
        f"- Causal chain complete: `{str(attempt.get('causal_chain_complete')).lower()}`",
        f"- Critical deviations: `{', '.join(attempt.get('critical_deviations') or []) or 'none'}`",
        "",
        "## Acceptance Rules",
        "",
    ]
    for key, value in _safe_dict(report.get("assumptions_and_stop_rules")).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Strategy Essentials",
            "",
        ]
    )
    for index, essential in enumerate(_safe_list(report.get("strategy_essentials")), start=1):
        lines.append(f"{index}. {essential}")
    lines.extend(
        [
            "",
            "## Final Metrics",
            "",
            "| Metric | Observed | Target | Pass |",
            "|---|---:|---:|---:|",
        ]
    )
    metrics = _safe_dict(report.get("final_metrics"))
    targets = _safe_dict(report.get("final_targets"))
    target_results = _safe_dict(report.get("final_target_results"))
    for key in ("final_turn", "num_cities", "total_population", "science_yield", "culture_yield", "era_score"):
        lines.append(f"| `{key}` | `{metrics.get(key)}` | `{targets.get(key)}` | `{str(target_results.get(key)).lower()}` |")
    lines.extend(["", "## Stage Scores", "", "| Stage | Score | Status | Milestone |", "|---|---:|---|---|"])
    for stage in _safe_list(report.get("stage_scores")):
        lines.append(f"| `{stage.get('stage_id')}` | `{stage.get('score')}` | `{stage.get('status')}` | {stage.get('milestone')} |")
    lines.extend(
        [
            "",
            "## Checkpoints",
            "",
            "| Node | Score | Status | Must Observe | Failure Criteria | Missing Observations |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for checkpoint in _safe_list(report.get("checkpoints")):
        missing = [
            str(obs.get("label"))
            for obs in _safe_list(checkpoint.get("observations"))
            if obs.get("observed") is not True
        ]
        lines.append(
            f"| `{checkpoint.get('node')}` | `{checkpoint.get('score')}` | `{checkpoint.get('status')}` | "
            f"{checkpoint.get('must_observe')} | {checkpoint.get('failure_criteria')} | "
            f"{'; '.join(missing) or 'none'} |"
        )
    lines.extend(["", "## Boundary", "", "- This report is read-only evidence evaluation.", "- It does not start Civ6, mutate saves, or merge strategy assets."])
    return "\n".join(lines)


def _render_window_markdown(report: dict[str, Any]) -> str:
    stop_rule = _safe_dict(report.get("stop_rule"))
    lines = [
        "# Human Demo T50 Contract v2 Attempt Window",
        "",
        f"- Valid attempts: `{report.get('valid_attempt_count')}`",
        f"- Stop recommended: `{str(stop_rule.get('stop_recommended')).lower()}`",
        f"- Repeated critical deviations: `{', '.join(stop_rule.get('repeated_critical_deviations') or []) or 'none'}`",
        f"- Required action: {stop_rule.get('required_action')}",
        "",
        "## Acceptance Rules",
        "",
    ]
    for key, value in _safe_dict(report.get("assumptions_and_stop_rules")).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Strategy Essentials",
            "",
        ]
    )
    for index, essential in enumerate(_safe_list(report.get("strategy_essentials")), start=1):
        lines.append(f"{index}. {essential}")
    lines.extend(
        [
            "",
            "## Attempt Summary",
            "",
            "| Episode | Success | Valid | Critical Deviations | Final Turn | Final Cities | Science | Culture | Era |",
            "|---|---:|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for attempt in _safe_list(report.get("attempts")):
        attempt_meta = _safe_dict(attempt.get("attempt"))
        metrics = _safe_dict(attempt.get("final_metrics"))
        lines.append(
            f"| `{attempt.get('episode_id')}` | `{str(attempt_meta.get('success')).lower()}` | "
            f"`{str(attempt_meta.get('valid_strategy_attempt')).lower()}` | "
            f"`{', '.join(attempt_meta.get('critical_deviations') or []) or 'none'}` | "
            f"`{metrics.get('final_turn')}` | `{metrics.get('num_cities')}` | `{metrics.get('science_yield')}` | `{metrics.get('culture_yield')}` | `{metrics.get('era_score')}` |"
        )
    stage_ids = [str(stage["stage_id"]) for stage in STAGES]
    lines.extend(["", "## Stage Scores", "", "| Episode | " + " | ".join(f"`{stage_id}`" for stage_id in stage_ids) + " |"])
    lines.append("|---|" + "|".join("---:" for _ in stage_ids) + "|")
    for attempt in _safe_list(report.get("attempts")):
        stages = {
            str(stage.get("stage_id")): f"{stage.get('status')} ({stage.get('score')})"
            for stage in _safe_list(attempt.get("stage_scores"))
        }
        lines.append(
            f"| `{attempt.get('episode_id')}` | "
            + " | ".join(f"`{stages.get(stage_id, 'missing')}`" for stage_id in stage_ids)
            + " |"
        )
    return "\n".join(lines)


def write_report(output_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_dumps(report) + "\n", encoding="utf-8")
    markdown_path = output_path.with_suffix(".md")
    markdown_path.write_text(render_markdown(report) + "\n", encoding="utf-8")
    report["outputs"] = {"json": str(output_path), "markdown": str(markdown_path)}
    output_path.write_text(json_dumps(report) + "\n", encoding="utf-8")
    return report


def _parse_episode_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--episode", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    episode_ids = _parse_episode_list(args.episode)
    if not episode_ids:
        print(json_dumps({"ok": False, "error": "at least one --episode is required"}), file=sys.stderr)
        raise SystemExit(2)
    try:
        report = (
            evaluate_episode_contract(episode_ids[0], workspace=args.workspace)
            if len(episode_ids) == 1
            else evaluate_attempt_window(episode_ids, workspace=args.workspace)
        )
        if args.output is not None:
            report = write_report(args.output, report)
    except (HumanDemoContractError, OSError, EpisodeStoreError, json.JSONDecodeError) as exc:
        print(json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json_dumps(report))


if __name__ == "__main__":
    main()
