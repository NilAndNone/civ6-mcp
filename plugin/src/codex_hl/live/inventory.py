from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codex_hl.live.actions import ACTION_REGISTRY, GAME_STATE_METHOD_LEVELS
from codex_hl.live.mutation_levels import ActionKind, MutationLevel


@dataclass(frozen=True)
class McpToolEntry:
    name: str
    line: int
    read_only_hint: bool
    destructive_hint: bool
    registered: bool
    mutation_level: MutationLevel
    action_kind: ActionKind
    game_state_methods: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameStateMethodEntry:
    name: str
    line: int
    mutation_level: MutationLevel
    registered_mutation: bool


@dataclass(frozen=True)
class DirectMutationCall:
    symbol: str
    call_path: str
    line: int
    mutation_level: MutationLevel
    source: str
    requires_future_gateway: bool


@dataclass(frozen=True)
class BoundaryPathEntry:
    name: str
    line: int
    mutation_level: MutationLevel
    source: str
    notes: str


@dataclass(frozen=True)
class MutationInventory:
    mcp_tools: tuple[McpToolEntry, ...]
    game_state_methods: tuple[GameStateMethodEntry, ...]
    observation_direct_mutations: tuple[DirectMutationCall, ...]
    boundary_paths: tuple[BoundaryPathEntry, ...]


OBSERVATION_BOUNDARY_SYMBOL_LEVELS: dict[str, MutationLevel] = {
    "save_game": MutationLevel.L4_BOUNDARY_RECOVERY,
    "load_game_save": MutationLevel.L4_BOUNDARY_RECOVERY,
    "front_end_load_game_save": MutationLevel.L4_BOUNDARY_RECOVERY,
    "connect_with_retry": MutationLevel.L4_BOUNDARY_RECOVERY,
    "connect": MutationLevel.L4_BOUNDARY_RECOVERY,
    "reconnect": MutationLevel.L4_BOUNDARY_RECOVERY,
    "disconnect": MutationLevel.L4_BOUNDARY_RECOVERY,
    "launch_game": MutationLevel.L4_BOUNDARY_RECOVERY,
    "kill_game": MutationLevel.L4_BOUNDARY_RECOVERY,
    "execute_read": MutationLevel.L4_BOUNDARY_RECOVERY,
    "execute_write": MutationLevel.L4_BOUNDARY_RECOVERY,
    "execute_in_state": MutationLevel.L4_BOUNDARY_RECOVERY,
}


BOUNDARY_PATH_NOTES: dict[str, str] = {
    "save_game": "Observation checkpoint save path via civ6_connector.game_lifecycle.save_game.",
    "load_save": "MCP save load by index.",
    "load_game_save": "MCP and observation save load by name.",
    "front_end_load_game_save": "Shared FrontEnd/LoadGameMenu Lua save load path.",
    "restart_and_load": "MCP recovery path that tries shared Lua load before GUI restart.",
    "load_save_from_menu": "MCP OCR/menu save load path.",
    "kill_game": "MCP and observation process kill path.",
    "launch_game": "MCP and observation process launch path.",
    "run_lua": "MCP arbitrary Lua escape hatch.",
    "GameConnection.execute_write": "Raw InGame Lua execution path used by GameState and observation recording.",
    "GameConnection.execute_read": "Raw GameCore Lua execution path used by GameState and observation recording.",
    "GameConnection.execute_in_state": "Raw state-index Lua execution path used by FrontEnd save loading.",
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _expr_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_path(node.value)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None


def _annotation_bool(decorator: ast.Call, key_name: str) -> bool:
    for keyword in decorator.keywords:
        if keyword.arg != "annotations" or not isinstance(keyword.value, ast.Dict):
            continue
        for key, value in zip(keyword.value.keys, keyword.value.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == key_name
                and isinstance(value, ast.Constant)
            ):
                return bool(value.value)
    return False


def _is_mcp_tool_decorator(decorator: ast.AST) -> ast.Call | None:
    if not isinstance(decorator, ast.Call):
        return None
    if _expr_path(decorator.func) == "mcp.tool":
        return decorator
    return None


def discover_mcp_tools(server_path: Path) -> tuple[McpToolEntry, ...]:
    """Return every @mcp.tool entry with current Phase 0 classification."""

    entries: list[McpToolEntry] = []
    for node in _parse(server_path).body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        tool_decorator = next(
            (
                call
                for decorator in node.decorator_list
                if (call := _is_mcp_tool_decorator(decorator)) is not None
            ),
            None,
        )
        if tool_decorator is None:
            continue
        read_only = _annotation_bool(tool_decorator, "readOnlyHint")
        destructive = _annotation_bool(tool_decorator, "destructiveHint")
        spec = ACTION_REGISTRY.get(node.name)
        if spec is None:
            entries.append(
                McpToolEntry(
                    name=node.name,
                    line=node.lineno,
                    read_only_hint=read_only,
                    destructive_hint=destructive,
                    registered=False,
                    mutation_level=MutationLevel.L0_READ,
                    action_kind=ActionKind.PURE_READ,
                )
            )
            continue
        entries.append(
            McpToolEntry(
                name=node.name,
                line=node.lineno,
                read_only_hint=read_only,
                destructive_hint=destructive,
                registered=True,
                mutation_level=spec.mutation_level,
                action_kind=spec.action_kind,
                game_state_methods=spec.game_state_methods,
            )
        )
    return tuple(entries)


def _pattern_literals(pattern: ast.pattern) -> tuple[str, ...]:
    if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Constant):
        if isinstance(pattern.value.value, str):
            return (pattern.value.value,)
    if isinstance(pattern, ast.MatchOr):
        values: list[str] = []
        for child in pattern.patterns:
            values.extend(_pattern_literals(child))
        return tuple(values)
    return ()


def discover_server_action_cases(server_path: Path, function_name: str) -> tuple[str, ...]:
    """Return string cases from a server.py action multiplexer match statement."""

    module = _parse(server_path)
    cases: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != function_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Match):
                continue
            for case in child.cases:
                cases.extend(_pattern_literals(case.pattern))
    return tuple(cases)


def discover_game_state_methods(game_state_path: Path) -> tuple[GameStateMethodEntry, ...]:
    module = _parse(game_state_path)
    entries: list[GameStateMethodEntry] = []
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "GameState":
            continue
        for child in node.body:
            if not isinstance(child, ast.AsyncFunctionDef):
                continue
            level = GAME_STATE_METHOD_LEVELS.get(child.name, MutationLevel.L0_READ)
            entries.append(
                GameStateMethodEntry(
                    name=child.name,
                    line=child.lineno,
                    mutation_level=level,
                    registered_mutation=child.name in GAME_STATE_METHOD_LEVELS,
                )
            )
    return tuple(entries)


def _classify_observation_path(call_path: str) -> tuple[str, MutationLevel] | None:
    symbol = call_path.rsplit(".", 1)[-1]
    if call_path.startswith("gs.") and symbol in GAME_STATE_METHOD_LEVELS:
        return symbol, GAME_STATE_METHOD_LEVELS[symbol]
    if call_path.startswith("gs.conn.") and symbol in OBSERVATION_BOUNDARY_SYMBOL_LEVELS:
        return symbol, OBSERVATION_BOUNDARY_SYMBOL_LEVELS[symbol]
    if call_path.startswith("conn.") and symbol in OBSERVATION_BOUNDARY_SYMBOL_LEVELS:
        return symbol, OBSERVATION_BOUNDARY_SYMBOL_LEVELS[symbol]
    if call_path.startswith("game_launcher.") and symbol in OBSERVATION_BOUNDARY_SYMBOL_LEVELS:
        return symbol, OBSERVATION_BOUNDARY_SYMBOL_LEVELS[symbol]
    if symbol in OBSERVATION_BOUNDARY_SYMBOL_LEVELS:
        return symbol, OBSERVATION_BOUNDARY_SYMBOL_LEVELS[symbol]
    return None


def discover_observation_direct_mutations(observation_path: Path) -> tuple[DirectMutationCall, ...]:
    module = _parse(observation_path)
    found: dict[tuple[int, str], DirectMutationCall] = {}

    class Visitor(ast.NodeVisitor):
        def _record(self, node: ast.AST, call_path: str | None) -> None:
            if call_path is None:
                return
            classified = _classify_observation_path(call_path)
            if classified is None:
                return
            symbol, level = classified
            line = getattr(node, "lineno", 0)
            found[(line, call_path)] = DirectMutationCall(
                symbol=symbol,
                call_path=call_path,
                line=line,
                mutation_level=level,
                source="observation.py",
                requires_future_gateway=level.is_game_mutation_or_higher(),
            )

        def visit_Call(self, node: ast.Call) -> None:
            self._record(node, _expr_path(node.func))
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            self._record(node, _expr_path(node))
            self.generic_visit(node)

    Visitor().visit(module)
    return tuple(sorted(found.values(), key=lambda call: (call.line, call.call_path)))


def _line_index_by_name(entries: tuple[McpToolEntry, ...]) -> dict[str, int]:
    return {entry.name: entry.line for entry in entries}


def _line_index_by_direct_call(calls: tuple[DirectMutationCall, ...]) -> dict[str, int]:
    lines: dict[str, int] = {}
    for call in calls:
        lines.setdefault(call.symbol, call.line)
    return lines


def _boundary_paths(
    mcp_tools: tuple[McpToolEntry, ...],
    direct_calls: tuple[DirectMutationCall, ...],
) -> tuple[BoundaryPathEntry, ...]:
    mcp_lines = _line_index_by_name(mcp_tools)
    direct_lines = _line_index_by_direct_call(direct_calls)
    names = [
        "save_game",
        "load_save",
        "load_game_save",
        "front_end_load_game_save",
        "restart_and_load",
        "load_save_from_menu",
        "kill_game",
        "launch_game",
        "run_lua",
        "GameConnection.execute_write",
        "GameConnection.execute_read",
        "GameConnection.execute_in_state",
    ]
    entries: list[BoundaryPathEntry] = []
    for name in names:
        spec = ACTION_REGISTRY.get(name)
        level = (
            spec.mutation_level
            if spec is not None
            else OBSERVATION_BOUNDARY_SYMBOL_LEVELS.get(
                name.rsplit(".", 1)[-1],
                MutationLevel.L4_BOUNDARY_RECOVERY,
            )
        )
        entries.append(
            BoundaryPathEntry(
                name=name,
                line=mcp_lines.get(name, direct_lines.get(name, 0)),
                mutation_level=level,
                source="server.py/observation.py/connection.py",
                notes=BOUNDARY_PATH_NOTES[name],
            )
        )
    return tuple(entries)


def build_mutation_inventory(
    *,
    server_path: Path,
    game_state_path: Path,
    observation_path: Path,
) -> MutationInventory:
    mcp_tools = discover_mcp_tools(server_path)
    game_state_methods = discover_game_state_methods(game_state_path)
    direct_calls = discover_observation_direct_mutations(observation_path)
    return MutationInventory(
        mcp_tools=mcp_tools,
        game_state_methods=game_state_methods,
        observation_direct_mutations=direct_calls,
        boundary_paths=_boundary_paths(mcp_tools, direct_calls),
    )


def render_markdown_inventory(inventory: MutationInventory) -> str:
    """Render a compact markdown view for docs/live_refactor/phase_0_inventory.md."""

    lines = [
        "# Phase 0 Mutation Inventory",
        "",
        "This inventory is descriptive only. It does not route or block any action.",
        "",
        "## MCP Tools",
        "",
        "| Tool | Level | Kind | Registered | Line | GameState methods |",
        "|---|---|---|---|---:|---|",
    ]
    for entry in inventory.mcp_tools:
        methods = ", ".join(entry.game_state_methods) or "-"
        lines.append(
            f"| `{entry.name}` | `{entry.mutation_level.value}` | `{entry.action_kind.value}` | "
            f"{'yes' if entry.registered else 'no'} | {entry.line} | {methods} |"
        )
    lines.extend(
        [
            "",
            "## Observation Direct Mutation Calls",
            "",
            "| Symbol | Level | Line | Path | Future Gateway |",
            "|---|---|---:|---|---|",
        ]
    )
    for call in inventory.observation_direct_mutations:
        lines.append(
            f"| `{call.symbol}` | `{call.mutation_level.value}` | {call.line} | "
            f"`{call.call_path}` | {'yes' if call.requires_future_gateway else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary Paths",
            "",
            "| Path | Level | Line | Notes |",
            "|---|---|---:|---|",
        ]
    )
    for entry in inventory.boundary_paths:
        lines.append(
            f"| `{entry.name}` | `{entry.mutation_level.value}` | {entry.line} | {entry.notes} |"
        )
    lines.append("")
    return "\n".join(lines)
