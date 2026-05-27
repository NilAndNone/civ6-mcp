"""Historic moments domain - Lua builders and parsers."""

from __future__ import annotations

from civ6_connector.lua._helpers import SENTINEL
from civ6_connector.lua.models import HistoricMoment


def build_historic_moments_query(min_interest_level: int = 1) -> str:
    """Query the in-game historic moment timeline.

    Must run in the InGame context. Firaxis' HistoricMoments UI reads the same
    source via ``Game.GetHistoryManager():GetAllMomentsData(player, min_level)``.
    """
    min_level = max(0, int(min_interest_level))
    return f"""
local me = Game.GetLocalPlayer()
local history = Game.GetHistoryManager and Game.GetHistoryManager() or nil
if history == nil then
    print("ERR|NO_HISTORY_MANAGER")
    print("{SENTINEL}")
    return
end

local function clean(value)
    if value == nil then return "" end
    return tostring(value):gsub("|", "/"):gsub("\\n", " ")
end

local function loc(value)
    if value == nil or value == "" then return "" end
    local ok, text = pcall(function() return Locale.Lookup(value) end)
    if ok and text ~= nil then return clean(text) end
    return clean(value)
end

local function data_type_name(dataType)
    if dataType == nil then return "" end
    local row = GameInfo.MomentDataTypes[dataType]
    if row == nil then return tostring(dataType) end
    return clean(row.MomentDataType or loc(row.Name) or dataType)
end

local function resolve_data(dataType, dataValue)
    if dataType == nil or dataValue == nil then return "" end
    local name = data_type_name(dataType)
    local ok, value = pcall(function()
        if name == "MOMENT_DATA_TARGET_PLAYER" or name == "MOMENT_DATA_CITY_STATE_PLAYER" then
            local cfg = PlayerConfigurations[dataValue]
            if cfg then return Locale.Lookup(cfg:GetCivilizationDescription()) end
        elseif name == "MOMENT_DATA_FEATURE" and GameInfo.Features[dataValue] then
            return Locale.Lookup(GameInfo.Features[dataValue].Name)
        elseif name == "MOMENT_DATA_UNIT" and GameInfo.Units[dataValue] then
            return Locale.Lookup(GameInfo.Units[dataValue].Name)
        elseif name == "MOMENT_DATA_TECHNOLOGY" and GameInfo.Technologies[dataValue] then
            return Locale.Lookup(GameInfo.Technologies[dataValue].Name)
        elseif name == "MOMENT_DATA_CIVIC" and GameInfo.Civics[dataValue] then
            return Locale.Lookup(GameInfo.Civics[dataValue].Name)
        elseif name == "MOMENT_DATA_GOVERNMENT" and GameInfo.Governments[dataValue] then
            return Locale.Lookup(GameInfo.Governments[dataValue].Name)
        elseif name == "MOMENT_DATA_PLAYER_ERA" or name == "MOMENT_DATA_TARGET_PLAYER_ERA" then
            if GameInfo.Eras[dataValue] then return Locale.Lookup(GameInfo.Eras[dataValue].Name) end
        end
        return tostring(dataValue)
    end)
    if ok then return clean(value) end
    return clean(dataValue)
end

local moments = history:GetAllMomentsData(me, {min_level})
print("COUNT|" .. tostring(moments and #moments or 0))
if moments then
    for _, momentData in ipairs(moments) do
        local momentInfo = GameInfo.Moments[momentData.Type]
        local eraType = ""
        if momentData.GameEra ~= nil and GameInfo.Eras[momentData.GameEra] then
            eraType = clean(GameInfo.Eras[momentData.GameEra].EraType)
        end
        local momentType = ""
        local name = ""
        local description = ""
        local interestLevel = 0
        if momentInfo then
            momentType = clean(momentInfo.MomentType)
            name = loc(momentInfo.Name)
            description = loc(momentInfo.Description)
            interestLevel = momentInfo.InterestLevel or 0
        end
        local line = table.concat({{
            "HMOMENT",
            clean(momentData.ID),
            clean(momentData.Turn),
            clean(momentData.GameEra),
            eraType,
            clean(momentData.ActingPlayer),
            clean(momentData.Type),
            momentType,
            name,
            description,
            clean(momentData.InstanceDescription),
            clean(momentData.EraScore or 0),
            clean(interestLevel),
            momentData.HasEverBeenCommemorated and "1" or "0"
        }}, "|")
        print(line)
        if momentData.ExtraData then
            for _, pair in ipairs(momentData.ExtraData) do
                print(table.concat({{
                    "HMDATA",
                    clean(momentData.ID),
                    clean(pair.DataType),
                    data_type_name(pair.DataType),
                    clean(pair.DataValue),
                    resolve_data(pair.DataType, pair.DataValue)
                }}, "|"))
            end
        end
    end
end
print("{SENTINEL}")
"""


def parse_historic_moments_response(lines: list[str]) -> list[HistoricMoment]:
    moments: dict[int, HistoricMoment] = {}
    order: list[int] = []
    pending_extra: dict[int, list[dict[str, object]]] = {}
    for line in lines:
        if line.startswith("ERR|"):
            raise ValueError(line)
        if line.startswith("HMDATA|"):
            parts = line.split("|")
            if len(parts) < 6:
                continue
            moment_id = int(parts[1])
            row = {
                "data_type": _int_or_text(parts[2]),
                "data_type_name": parts[3],
                "data_value": _int_or_text(parts[4]),
                "resolved": parts[5],
            }
            if moment_id in moments:
                moments[moment_id].extra_data.append(row)
            else:
                pending_extra.setdefault(moment_id, []).append(row)
            continue
        if not line.startswith("HMOMENT|"):
            continue
        parts = line.split("|")
        if len(parts) < 14:
            continue
        moment_id = int(parts[1])
        moment = HistoricMoment(
            moment_id=moment_id,
            turn=int(parts[2]),
            game_era=int(parts[3]) if parts[3] else -1,
            game_era_type=parts[4],
            acting_player=int(parts[5]) if parts[5] else -1,
            moment_type_id=int(parts[6]) if parts[6] else 0,
            moment_type=parts[7],
            name=parts[8],
            description=parts[9],
            instance_description=parts[10],
            era_score=int(parts[11]) if parts[11] else 0,
            interest_level=int(parts[12]) if parts[12] else 0,
            has_ever_been_commemorated=parts[13] == "1",
            extra_data=pending_extra.pop(moment_id, []),
        )
        moments[moment_id] = moment
        order.append(moment_id)
    return [moments[moment_id] for moment_id in order]


def _int_or_text(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value
