"""Build a Civ6 factual Markdown knowledge base for model retrieval."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
FANDOM_API = "https://civilization.fandom.com/api.php"
FANDOM_PAGE = "https://civilization.fandom.com/wiki/"
DEFAULT_OUT = WORKSPACE_ROOT / "outputs" / "civ6-wiki"
DEFAULT_CACHE = WORKSPACE_ROOT / "outputs" / "civ6-wiki-cache"
DEFAULT_PLUGIN_KB = WORKSPACE_ROOT / "plugin" / "assets" / "codex_hl" / "knowledge" / "civ6-wiki"
DEFAULT_GAME_ROOT = Path(r"O:\SteamLibrary\steamapps\common\Sid Meier's Civilization VI")
USER_AGENT = "codex-hl-civ6-wiki-builder/0.1"


CATEGORY_SPECS: dict[str, str] = {
    "civilizations": "Civilizations_(Civ6)",
    "leaders": "Leaders_(Civ6)",
    "technologies": "Technologies_(Civ6)",
    "civics": "Civics_(Civ6)",
    "units": "Units_(Civ6)",
    "buildings": "Buildings_(Civ6)",
    "districts": "Districts_(Civ6)",
    "wonders": "Wonders_(Civ6)",
    "policies": "Policy_Cards_(Civ6)",
    "resources": "Resources_(Civ6)",
    "religion": "Religions_(Civ6)",
    "beliefs": "Beliefs_(Civ6)",
    "city-states": "City-states_(Civ6)",
    "game-modes": "Game_modes_(Civ6)",
    "core-mechanics": "Game_concepts_(Civ6)",
}

LIST_PAGE_SPECS: dict[str, str] = {
    "List of technologies in Civ6": "technologies",
    "List of civics in Civ6": "civics",
    "List of units in Civ6": "units",
    "List of buildings in Civ6": "buildings",
    "List of districts in Civ6": "districts",
    "List of wonders in Civ6": "wonders",
    "List of resources in Civ6": "resources",
    "Terrain (Civ6)": "terrain",
    "Feature (Civ6)": "features",
    "List of religions in Civ6": "religion",
    "List of beliefs in Civ6": "beliefs",
    "List of city-states in Civ6": "city-states",
    "Victory (Civ6)": "victory-types",
    "Game mode (Civ6)": "game-modes",
}

EXPLICIT_PAGES: dict[str, str] = {
    "Apocalypse (Civ6)": "game-modes",
    "Secret Societies (Civ6)": "game-modes",
    "Tech and Civic Shuffle (Civ6)": "game-modes",
    "Dramatic Ages (Civ6)": "game-modes",
    "Heroes & Legends (Civ6)": "game-modes",
    "Monopolies and Corporations (Civ6)": "game-modes",
    "Barbarian Clans (Civ6)": "game-modes",
    "Zombie Defense (Civ6)": "game-modes",
    "Science Victory (Civ6)": "victory-types",
    "Culture Victory (Civ6)": "victory-types",
    "Domination Victory (Civ6)": "victory-types",
    "Religious Victory (Civ6)": "victory-types",
    "Diplomatic Victory (Civ6)": "victory-types",
    "Score Victory (Civ6)": "victory-types",
}

SAMPLE_PAGES: dict[str, str] = {
    "Babylonian (Civ6)": "civilizations",
    "Hammurabi (Civ6)": "leaders",
    "Archery (Civ6)": "technologies",
    "Code of Laws (Civ6)": "civics",
    "Archer (Civ6)": "units",
    "Campus (Civ6)": "districts",
    "Apocalypse (Civ6)": "game-modes",
}

TEMPLATE_CATEGORY: dict[str, str] = {
    "tech": "technologies",
    "civic": "civics",
    "civ": "civilizations",
    "leader": "leaders",
    "unit": "units",
    "building": "buildings",
    "district": "districts",
    "district_": "districts",
    "wonder": "wonders",
    "resource": "resources",
    "terrain": "terrain",
    "feature": "features",
    "belief": "beliefs",
    "religion": "religion",
    "policycard": "policies",
    "policy card": "policies",
    "government": "governments",
}

FACT_FIELD_LABELS: dict[str, str] = {
    "name": "Name",
    "era": "Era",
    "game": "Introduced in",
    "cost": "Cost",
    "production_cost": "Production cost",
    "maintenance": "Maintenance",
    "reqs": "Requires",
    "leadsto": "Leads to",
    "eureka": "Eureka",
    "inspiration": "Inspiration",
    "units": "Units",
    "buildings": "Buildings",
    "districts": "Districts",
    "wonders": "Wonders",
    "infrastructure": "Infrastructure",
    "policies": "Policies",
    "ability-name": "Ability",
    "ability-description": "Ability description",
    "bonus-name": "Leader ability",
    "bonus-description": "Leader ability description",
    "agenda-name": "Agenda",
    "agenda-description": "Agenda description",
    "unit": "Unique unit",
    "building": "Unique building",
    "district": "Unique district",
    "improvement": "Unique improvement",
    "leader": "Leader",
    "civ": "Civilization",
    "advance_required": "Required technology/civic",
    "plunder": "Plunder yield",
    "great_person_points": "Great person points",
    "adjacency_bonus": "Adjacency bonus",
}

SCENARIO_MARKERS = (
    "scenario",
    "war machine",
    "black death",
    "pirates",
    "civ royale",
    "outback tycoon",
    "path to nirvana",
    "gifts of the nile",
    "jadwiga",
    "viking",
    "conquests of alexander",
    "scenario-specific",
)

DROP_SECTION_TITLES = {
    "strategy",
    "civilopedia entry",
    "historical context",
    "trivia",
    "gallery",
    "videos",
    "see also",
    "references",
    "external links",
}

SAMPLE_FIXTURES: dict[str, str] = {
    "Archery (Civ6)": """{{Tech (Civ6)
|era = Ancient
|name = Archery
|units = Archer
|cost = 50
|reqs = Animal Husbandry
|eureka = Kill a unit with a {{Link6|Slinger}}.
|leadsto = Horseback Riding
}}
'''Archery''' is an [[Ancient Era (Civ6)|Ancient Era]] [[Technology (Civ6)|technology]] in ''[[Civilization VI]]''. It can be hurried by killing an enemy with a [[Slinger (Civ6)|Slinger]].

== Strategy ==
This subjective strategy section is intentionally ignored by the builder.
""",
    "Code of Laws (Civ6)": """{{Civic (Civ6)
|era = Ancient
|name = Code of Laws
|cost = 20
|leadsto = Craftsmanship, Foreign Trade
|policies = Discipline, God King, Survey, Urban Planning
|inspiration = None
}}
'''Code of Laws''' is an [[Ancient Era (Civ6)|Ancient Era]] [[Civic (Civ6)|civic]] in ''[[Civilization VI]]''.
""",
    "Babylonian (Civ6)": """{{Civ (Civ6)
|name = Babylon
|game = Babylon Pack
|ability-name = Enuma Anu Enlil
|ability-description = {{Eureka6}}s instantly unlock their respective {{Link6|technologies}}. -50% {{Science6}} per turn.
|unit = Sabum Kibittum
|building = Palgum
|leader = Hammurabi
}}
The '''Babylonian''' people represent a civilization in ''[[Civilization VI]]''.
""",
    "Hammurabi (Civ6)": """{{Leader (Civ6)
|game = Babylon Pack
|civ = Babylonian
|bonus-name = Ninu Ilu Sirum
|bonus-description = Upon building each type of specialty {{District6}}, except the [[Government Plaza (Civ6)|Government Plaza]], for the first time, instantly receives the lowest-cost building that can be built in that district.
|agenda-name = Cradle of Civilization
|agenda-description = Tries to build every type of District.
}}
'''Hammurabi''' is a leader for Babylon in ''[[Civilization VI]]''.
""",
    "Archer (Civ6)": """{{Unit (Civ6)
|name = Archer
|class = Ranged
|cost = 60
|maintenance = 1
|required_tech = Archery
}}
The '''Archer''' is an [[Ancient Era (Civ6)|Ancient Era]] ranged unit in ''[[Civilization VI]]''.
""",
    "Campus (Civ6)": """{{District_(Civ6)
|era = Ancient
|advance_required = Writing
|production_cost = 54
|maintenance = 1
|great_person_points = +1 {{Scientist6}} point per turn.
|adjacency_bonus = +1 {{Science6}} from each adjacent Mountain tile.
}}
The '''Campus''' is a specialty district in ''[[Civilization VI]]'', dedicated to Science.
""",
    "Apocalypse (Civ6)": """{{BackArrow|Game mode (Civ6)|Back to Game Modes}}
'''Apocalypse''' is the first [[Game mode (Civ6)|game mode]] in ''[[Civilization VI]]'', introduced in the [[Maya & Gran Colombia Pack (Civ6)|Maya & Gran Colombia Pack]]. It focuses on disasters and climate change and requires the ''[[Civilization VI: Gathering Storm|Gathering Storm]]'' expansion.

== Mechanics ==
The mode increases disaster intensity and adds the Soothsayer unit, Appease the Gods competition, and an end-game Apocalypse phase.
""",
}


@dataclass(frozen=True)
class SourceCandidate:
    title: str
    category: str


@dataclass
class WikiPage:
    title: str
    category: str
    source_url: str
    fields: dict[str, str]
    summary: str
    related_pages: list[str]
    aliases: list[str] = field(default_factory=list)
    wiki_categories: list[str] = field(default_factory=list)
    local_ids: list[str] = field(default_factory=list)
    expansion_or_mode: str | None = None
    validation_notes: list[str] = field(default_factory=list)
    path: str = ""


@dataclass
class LocalEntity:
    category: str
    entity_id: str
    name: str
    attrs: dict[str, str]
    source_file: str
    expansion_or_mode: str


@dataclass
class LocalReference:
    root: Path
    present: bool
    entities_by_category: dict[str, list[LocalEntity]] = field(default_factory=dict)
    file_count: int = 0
    text_file_count: int = 0
    data_file_count: int = 0

    def find(self, category: str, names: list[str]) -> LocalEntity | None:
        candidates = self.entities_by_category.get(category, [])
        wanted = {normalize_key(name) for name in names if name}
        for entity in candidates:
            entity_names = {normalize_key(entity.name), normalize_key(entity.entity_id)}
            if wanted & entity_names:
                return entity
        return None


class FandomClient:
    def __init__(
        self,
        *,
        api_url: str = FANDOM_API,
        rate_limit_seconds: float = 0.5,
        max_retries: int = 4,
    ) -> None:
        self.api_url = api_url
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max(1, max_retries)
        self._last_request_at = 0.0

    def query(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            if self.rate_limit_seconds > 0:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self.rate_limit_seconds:
                    time.sleep(self.rate_limit_seconds - elapsed)
            request = urllib.request.Request(
                f"{self.api_url}?{query}",
                headers={"User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    data = json.loads(response.read().decode("utf-8"))
                self._last_request_at = time.monotonic()
                if "error" in data:
                    raise RuntimeError(f"Fandom API error: {data['error']}")
                return data
            except Exception as exc:  # pragma: no cover - network variability
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(2**attempt, 10))
        context = {
            key: params.get(key)
            for key in ("action", "list", "prop", "titles", "cmtitle")
            if key in params
        }
        raise RuntimeError(
            f"Fandom API request failed after {self.max_retries} attempts for {context}: {last_error}"
        ) from last_error

    def category_members(self, category: str) -> list[str]:
        titles: list[str] = []
        params: dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmnamespace": 0,
            "cmlimit": 500,
            "format": "json",
        }
        while True:
            data = self.query(params)
            members = data.get("query", {}).get("categorymembers", [])
            titles.extend(member["title"] for member in members if "title" in member)
            cont = data.get("continue")
            if not cont:
                break
            params.update(cont)
        return titles

    def page_links(self, title: str) -> list[str]:
        titles: list[str] = []
        params: dict[str, Any] = {
            "action": "query",
            "prop": "links",
            "titles": title,
            "plnamespace": 0,
            "pllimit": 500,
            "format": "json",
        }
        while True:
            data = self.query(params)
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                titles.extend(link["title"] for link in page.get("links", []) if "title" in link)
            cont = data.get("continue")
            if not cont:
                break
            params.update(cont)
        return titles

    def fetch_pages(self, titles: list[str], *, batch_size: int = 1) -> dict[str, tuple[str, list[str]]]:
        result: dict[str, tuple[str, list[str]]] = {}
        for index in range(0, len(titles), batch_size):
            batch = titles[index : index + batch_size]
            data = self.query(
                {
                    "action": "query",
                    "prop": "revisions|categories",
                    "titles": "|".join(batch),
                    "rvprop": "content",
                    "rvslots": "main",
                    "cllimit": 500,
                    "format": "json",
                }
            )
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                title = page.get("title")
                if not title or "missing" in page:
                    continue
                revisions = page.get("revisions", [])
                if not revisions:
                    continue
                revision = revisions[0]
                slots = revision.get("slots", {})
                main = slots.get("main", {})
                content = main.get("*", revision.get("*", ""))
                categories = [
                    cat.get("title", "").removeprefix("Category:")
                    for cat in page.get("categories", [])
                    if cat.get("title")
                ]
                result[title] = (content, categories)
        return result

    def fetch_page(self, title: str) -> tuple[str, list[str]]:
        pages = self.fetch_pages([title], batch_size=1)
        if title in pages:
            return pages[title]
        normalized = next(iter(pages.values()), None)
        if normalized:
            return normalized
        raise RuntimeError(f"Fandom page not found: {title}")


def normalize_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"\(civ6\)", "", ascii_value, flags=re.IGNORECASE)
    ascii_value = re.sub(r"[^a-zA-Z0-9]+", "", ascii_value)
    return ascii_value.lower()


def slugify(value: str) -> str:
    base = value.replace("(Civ6)", "").strip()
    ascii_value = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def page_url(title: str) -> str:
    return FANDOM_PAGE + urllib.parse.quote(title.replace(" ", "_"))


def display_title(title: str) -> str:
    return title.replace("(Civ6)", "").strip()


def template_base_name(template_name: str) -> str:
    base = template_name.strip().lower()
    base = re.sub(r"\s*\(civ6\)\s*", "", base)
    base = base.strip("_ ")
    return base


def extract_first_template(wikitext: str) -> tuple[str, str, str]:
    text = wikitext.lstrip()
    if not text.startswith("{{"):
        return "", "", wikitext
    depth = 0
    index = 0
    while index < len(text) - 1:
        pair = text[index : index + 2]
        if pair == "{{":
            depth += 1
            index += 2
            continue
        if pair == "}}":
            depth -= 1
            index += 2
            if depth == 0:
                raw = text[2 : index - 2]
                rest = text[index:]
                first_line = raw.splitlines()[0] if raw.splitlines() else raw
                return first_line.strip(), raw, rest
            continue
        index += 1
    return "", "", wikitext


def parse_template_fields(wikitext: str) -> tuple[str, dict[str, str], str]:
    template_name, raw, rest = extract_first_template(wikitext)
    if not raw:
        return "", {}, wikitext
    fields: dict[str, str] = {}
    current_key: str | None = None
    current_value: list[str] = []
    for line in raw.splitlines()[1:]:
        if line.startswith("|") and "=" in line:
            if current_key:
                fields[current_key] = clean_wikitext("\n".join(current_value).strip())
            key, value = line[1:].split("=", 1)
            current_key = key.strip()
            current_value = [value.strip()]
        elif current_key:
            current_value.append(line)
    if current_key:
        fields[current_key] = clean_wikitext("\n".join(current_value).strip())
    return template_name, fields, rest


def clean_wikitext(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    value = re.sub(r"<ref[^>]*>.*?</ref>", "", value, flags=re.DOTALL | re.IGNORECASE)
    value = re.sub(r"<ref[^/]*/>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[\[File:[^\]]+\]\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[\[Image:[^\]]+\]\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{Link6\|([^}|]+)(?:\|[^}]*)?\}\}", r"\1", value)
    value = re.sub(r"\{\{([^{}|]+)6\}\}", lambda m: split_camel(m.group(1)), value)
    value = re.sub(r"\{\{([^{}|]+)\|([^{}]+?)\}\}", lambda m: m.group(2).split("|")[-1], value)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"'''?", "", value)
    value = re.sub(r"<br\s*/?>", "; ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\[ICON_([A-Za-z_]+)\]", lambda m: split_camel(m.group(1).replace("_", " ")), value)
    value = value.replace("&nbsp;", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def split_camel(value: str) -> str:
    value = value.replace("_", " ")
    value = re.sub(r"(?<!^)(?=[A-Z])", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_sections(wikitext: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"lead": []}
    current = "lead"
    for line in wikitext.splitlines():
        match = re.match(r"^\s*==+\s*(.*?)\s*==+\s*$", line)
        if match:
            current = clean_wikitext(match.group(1)).lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def extract_summary(rest: str, *, fallback_title: str, category: str) -> str:
    sections = extract_sections(rest)
    lead = clean_wikitext(sections.get("lead", ""))
    paragraphs = [paragraph.strip() for paragraph in lead.split("\n\n") if paragraph.strip()]
    if paragraphs:
        return paragraphs[0]
    for name, body in sections.items():
        if name in DROP_SECTION_TITLES:
            continue
        cleaned = clean_wikitext(body)
        paragraphs = [paragraph.strip() for paragraph in cleaned.split("\n\n") if paragraph.strip()]
        if paragraphs:
            return paragraphs[0]
    return f"{display_title(fallback_title)} is a {category.replace('-', ' ')} entry for Civilization VI."


def extract_related(wikitext: str, title: str) -> list[str]:
    related: list[str] = []
    for match in re.finditer(r"\[\[([^|\]#]+)(?:#[^|\]]*)?(?:\|[^\]]+)?\]\]", wikitext):
        link = match.group(1).strip()
        if link == title:
            continue
        if "(Civ6)" not in link and not link.startswith("Civilization VI"):
            continue
        if is_scenario_title(link, []):
            continue
        if link not in related:
            related.append(link)
        if len(related) >= 12:
            break
    return related


def is_scenario_title(title: str, wiki_categories: list[str]) -> bool:
    haystack = " ".join([title, *wiki_categories]).lower()
    return any(marker in haystack for marker in SCENARIO_MARKERS)


def is_content_title(title: str) -> bool:
    if ":" in title:
        return False
    if title.startswith("List of "):
        return False
    if "/" in title:
        return False
    return "(Civ6)" in title or title.startswith("Civilization VI")


def infer_category(template_name: str, fields: dict[str, str], source_category: str, title: str) -> str:
    base = template_base_name(template_name)
    if base in TEMPLATE_CATEGORY:
        return TEMPLATE_CATEGORY[base]
    if title in EXPLICIT_PAGES:
        return EXPLICIT_PAGES[title]
    title_lower = title.lower()
    if "victory" in title_lower:
        return "victory-types"
    if "terrain" in title_lower:
        return "terrain"
    if "feature" in title_lower:
        return "features"
    if "game mode" in title_lower:
        return "game-modes"
    if "ability-name" in fields:
        return "civilizations"
    if "bonus-name" in fields:
        return "leaders"
    return source_category


def build_aliases(title: str, fields: dict[str, str]) -> list[str]:
    aliases: list[str] = []
    base = display_title(title)
    aliases.append(base)
    if fields.get("name") and fields["name"] not in aliases:
        aliases.append(fields["name"])
    if base.endswith("ian"):
        root = base.removesuffix("ian")
        if root and root not in aliases:
            aliases.append(root)
    return aliases


def build_page(title: str, source_category: str, wikitext: str, wiki_categories: list[str]) -> WikiPage | None:
    if is_scenario_title(title, wiki_categories):
        return None
    template_name, fields, rest = parse_template_fields(wikitext)
    category = infer_category(template_name, fields, source_category, title)
    summary = extract_summary(rest, fallback_title=title, category=category)
    return WikiPage(
        title=display_title(title),
        category=category,
        source_url=page_url(title),
        fields=fields,
        summary=summary,
        related_pages=extract_related(wikitext, title),
        aliases=build_aliases(title, fields),
        wiki_categories=wiki_categories,
        expansion_or_mode=fields.get("game") or ("Game mode" if category == "game-modes" else None),
    )


def collect_source_candidates(client: FandomClient, *, sample_only: bool, no_network: bool) -> list[SourceCandidate]:
    if sample_only or no_network:
        return [SourceCandidate(title, category) for title, category in SAMPLE_PAGES.items()]

    candidates: dict[str, str] = {}
    for category, fandom_category in CATEGORY_SPECS.items():
        for title in client.category_members(fandom_category):
            if is_content_title(title):
                candidates.setdefault(title, category)

    for list_page, category in LIST_PAGE_SPECS.items():
        for title in client.page_links(list_page):
            if is_content_title(title):
                candidates.setdefault(title, category)

    for title, category in EXPLICIT_PAGES.items():
        candidates[title] = category

    return [SourceCandidate(title, category) for title, category in sorted(candidates.items())]


def load_page_sources(
    client: FandomClient,
    candidates: list[SourceCandidate],
    *,
    no_network: bool,
    cache_dir: Path | None = None,
) -> dict[str, tuple[str, list[str]]]:
    if no_network:
        return {title: (text, []) for title, text in SAMPLE_FIXTURES.items()}
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    sources: dict[str, tuple[str, list[str]]] = {}
    for candidate in candidates:
        cache_path = page_cache_path(cache_dir, candidate.title) if cache_dir else None
        if cache_path and cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            sources[candidate.title] = (payload["wikitext"], payload.get("categories", []))
            continue
        wikitext, categories = client.fetch_page(candidate.title)
        sources[candidate.title] = (wikitext, categories)
        if cache_path:
            cache_payload = {
                "title": candidate.title,
                "source_url": page_url(candidate.title),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "categories": categories,
                "wikitext": wikitext,
            }
            cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")
    return sources


def page_cache_path(cache_dir: Path | None, title: str) -> Path | None:
    if cache_dir is None:
        return None
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
    return cache_dir / f"{slugify(title)}-{digest}.json"


def strip_namespace(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_xml(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        return None
    except OSError:
        return None


def load_local_text(game_root: Path) -> tuple[dict[str, str], int]:
    texts: dict[str, str] = {}
    text_files = list(game_root.glob("Base/Assets/Text/en_US/*.xml")) + list(game_root.glob("DLC/*/Text/en_US/*.xml"))
    for path in text_files:
        root = read_xml(path)
        if root is None:
            continue
        for row in root.iter():
            if row.tag != "Row":
                continue
            tag = row.attrib.get("Tag")
            text_node = row.find("Text")
            if tag and text_node is not None and text_node.text:
                texts[tag] = clean_game_text(text_node.text)
    return texts, len(text_files)


def clean_game_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\[ICON_([A-Za-z_]+)\]", lambda m: split_camel(m.group(1).replace("_", " ")), value)
    value = re.sub(r"\[NEWLINE\]", " ", value)
    value = re.sub(r"\[[^\]]+\]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def local_entity_specs() -> dict[str, tuple[str, str, str, tuple[str, ...]]]:
    return {
        "Technologies": ("technologies", "TechnologyType", "Name", ("Cost", "EraType")),
        "Civics": ("civics", "CivicType", "Name", ("Cost", "EraType")),
        "Units": ("units", "UnitType", "Name", ("Cost", "Maintenance", "BaseMoves", "Combat", "RangedCombat", "Range")),
        "Buildings": ("buildings", "BuildingType", "Name", ("Cost", "Maintenance", "PrereqTech", "PrereqCivic")),
        "Districts": ("districts", "DistrictType", "Name", ("Cost", "Maintenance", "PrereqTech", "PrereqCivic")),
        "Resources": ("resources", "ResourceType", "Name", ("ResourceClassType", "Frequency")),
        "Terrains": ("terrain", "TerrainType", "Name", ("MovementCost", "DefenseModifier")),
        "Features": ("features", "FeatureType", "Name", ("MovementChange", "DefenseModifier")),
        "Beliefs": ("beliefs", "BeliefType", "Name", ("BeliefClassType",)),
        "Governments": ("governments", "GovernmentType", "Name", ("OtherGovernmentIntolerance",)),
        "Policies": ("policies", "PolicyType", "Name", ("GovernmentSlotType", "PrereqCivic")),
        "Civilizations": ("civilizations", "CivilizationType", "Name", ("StartingCivilizationLevelType",)),
        "Leaders": ("leaders", "LeaderType", "Name", ("InheritFrom",)),
        "Victories": ("victory-types", "VictoryType", "Name", ("CriticalPercentage",)),
        "GameCapabilities": ("game-modes", "GameCapability", "Name", ()),
    }


def load_local_reference(game_root: Path) -> LocalReference:
    ref = LocalReference(root=game_root, present=game_root.exists())
    if not ref.present:
        return ref
    texts, text_count = load_local_text(game_root)
    ref.text_file_count = text_count
    specs = local_entity_specs()
    data_files = list(game_root.glob("Base/Assets/Gameplay/Data/*.xml")) + list(game_root.glob("DLC/*/Data/*.xml"))
    ref.data_file_count = len(data_files)
    ref.file_count = text_count + len(data_files)
    for path in data_files:
        root = read_xml(path)
        if root is None:
            continue
        expansion_or_mode = infer_local_package(path, game_root)
        for table in root:
            spec = specs.get(table.tag)
            if not spec:
                continue
            category, id_attr, name_attr, tracked_attrs = spec
            for row in table:
                if row.tag not in {"Row", "Replace"}:
                    continue
                entity_id = row.attrib.get(id_attr)
                if not entity_id:
                    continue
                raw_name = row.attrib.get(name_attr, entity_id)
                name = texts.get(raw_name, raw_name)
                attrs = {key: value for key, value in row.attrib.items() if key in tracked_attrs}
                ref.entities_by_category.setdefault(category, []).append(
                    LocalEntity(
                        category=category,
                        entity_id=entity_id,
                        name=name,
                        attrs=attrs,
                        source_file=strip_namespace(path, game_root),
                        expansion_or_mode=expansion_or_mode,
                    )
                )
    return ref


def infer_local_package(path: Path, game_root: Path) -> str:
    rel = path.relative_to(game_root)
    if rel.parts[0] == "Base":
        return "Base game"
    if rel.parts[0] == "DLC" and len(rel.parts) > 1:
        return rel.parts[1]
    return rel.parts[0]


def normalize_era(value: str) -> str:
    return value.removeprefix("ERA_").replace("_", " ").title()


def validate_pages(pages: list[WikiPage], local_ref: LocalReference) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not local_ref.present:
        findings.append(
            {
                "page": "(local game data)",
                "field": "game_root",
                "wiki_value": "",
                "local_value": f"missing: {local_ref.root}",
                "local_file": "",
            }
        )
        return findings

    for page in pages:
        names = [page.title, *page.aliases]
        for key in ("name", "civ"):
            if page.fields.get(key):
                names.append(page.fields[key])
        local = local_ref.find(page.category, names)
        if not local:
            page.validation_notes.append("No matching local game-data entity found for this page category/name.")
            continue
        page.local_ids.append(local.entity_id)
        if not page.expansion_or_mode:
            page.expansion_or_mode = local.expansion_or_mode
        compare_field(page, local, findings, wiki_key="cost", local_key="Cost")
        compare_field(page, local, findings, wiki_key="production_cost", local_key="Cost")
        if page.fields.get("era") and local.attrs.get("EraType"):
            wiki_era = page.fields["era"]
            local_era = normalize_era(local.attrs["EraType"])
            if normalize_key(wiki_era) != normalize_key(local_era):
                findings.append(
                    {
                        "page": page.title,
                        "field": "era",
                        "wiki_value": wiki_era,
                        "local_value": local_era,
                        "local_file": local.source_file,
                    }
                )
    return findings


def compare_field(
    page: WikiPage,
    local: LocalEntity,
    findings: list[dict[str, str]],
    *,
    wiki_key: str,
    local_key: str,
) -> None:
    wiki_value = page.fields.get(wiki_key)
    local_value = local.attrs.get(local_key)
    if not wiki_value or not local_value:
        return
    wiki_number = re.search(r"\d+", wiki_value)
    local_number = re.search(r"\d+", local_value)
    if wiki_number and local_number and wiki_number.group(0) != local_number.group(0):
        findings.append(
            {
                "page": page.title,
                "field": wiki_key,
                "wiki_value": wiki_value,
                "local_value": local_value,
                "local_file": local.source_file,
            }
        )


def write_outputs(
    out_dir: Path,
    pages: list[WikiPage],
    findings: list[dict[str, str]],
    *,
    local_ref: LocalReference,
    source_count: int,
    excluded_count: int,
    sample_only: bool,
    no_network: bool,
) -> dict[str, Any]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "pages").mkdir(parents=True, exist_ok=True)

    slugs_by_path: set[str] = set()
    for page in pages:
        slug = slugify(page.title)
        rel = Path("pages") / page.category / f"{slug}.md"
        while rel.as_posix() in slugs_by_path:
            slug = f"{slug}-{hashlib.sha1(page.source_url.encode('utf-8')).hexdigest()[:8]}"
            rel = Path("pages") / page.category / f"{slug}.md"
        slugs_by_path.add(rel.as_posix())
        page.path = rel.as_posix()
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_page(page), encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "Civilization Wiki/Fandom",
            "api_url": FANDOM_API,
            "entry_url": "https://civilization.fandom.com/wiki/Civilization_VI",
            "mode": "fixture" if no_network else "fandom_api",
        },
        "scope": {
            "included": sorted({page.category for page in pages}),
            "excluded": [
                "scenarios",
                "scenario-specific civilizations, units, technologies, civics, maps, and rules",
                "strategy advice and subjective rankings",
                "images and icons",
            ],
            "sample_only": sample_only,
        },
        "local_game_data": {
            "root": str(local_ref.root),
            "present": local_ref.present,
            "file_count": local_ref.file_count,
            "text_file_count": local_ref.text_file_count,
            "data_file_count": local_ref.data_file_count,
        },
        "counts": {
            "source_candidates": source_count,
            "pages": len(pages),
            "excluded_pages": excluded_count,
            "validation_findings": len(findings),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "pages_index.json").write_text(
        json.dumps([page_index_entry(page) for page in pages], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_rag_chunks(out_dir / "rag_chunks.jsonl", pages)
    (out_dir / "validation_report.md").write_text(
        render_validation_report(findings, pages, local_ref),
        encoding="utf-8",
    )
    (out_dir / "index.md").write_text(render_index(pages, manifest), encoding="utf-8")
    write_category_indexes(out_dir, pages)
    return manifest


def render_page(page: WikiPage) -> str:
    lines = [
        f"# {page.title}",
        "",
        f"- Category: {page.category}",
        f"- Source: [{page.source_url}]({page.source_url})",
    ]
    if page.expansion_or_mode:
        lines.append(f"- Introduced in: {page.expansion_or_mode}")
    if page.aliases:
        lines.append(f"- Aliases: {', '.join(page.aliases)}")
    if page.local_ids:
        lines.append(f"- Local game IDs: {', '.join(page.local_ids)}")
    lines.extend(["", "## Summary", "", page.summary, "", "## Key Facts", ""])
    facts = [(FACT_FIELD_LABELS.get(key, split_camel(key)), value) for key, value in page.fields.items() if value]
    if facts:
        for label, value in facts:
            lines.append(f"- {label}: {value}")
    else:
        lines.append("- No structured template fields were available; summary text is sourced from the page lead/mechanics sections.")
    if page.related_pages:
        lines.extend(["", "## Related Entries", ""])
        for related in page.related_pages[:12]:
            lines.append(f"- {display_title(related)}")
    lines.extend(["", "## Validation Notes", ""])
    if page.validation_notes:
        lines.extend(f"- {note}" for note in page.validation_notes)
    else:
        lines.append("- No local game-data conflict recorded during the latest build.")
    lines.append("")
    return "\n".join(lines)


def page_index_entry(page: WikiPage) -> dict[str, Any]:
    return {
        "id": f"{page.category}/{slugify(page.title)}",
        "title": page.title,
        "category": page.category,
        "aliases": page.aliases,
        "source_url": page.source_url,
        "path": page.path,
        "local_ids": page.local_ids,
        "expansion_or_mode": page.expansion_or_mode,
        "related_pages": [display_title(title) for title in page.related_pages],
    }


def chunk_text(page: WikiPage) -> str:
    parts = [page.summary]
    for key, value in page.fields.items():
        if value:
            parts.append(f"{FACT_FIELD_LABELS.get(key, split_camel(key))}: {value}")
    if page.related_pages:
        parts.append("Related entries: " + ", ".join(display_title(title) for title in page.related_pages[:8]))
    return "\n".join(parts)


def write_rag_chunks(path: Path, pages: list[WikiPage]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for page in pages:
            text = chunk_text(page)
            chunks = split_chunks(text)
            for index, chunk in enumerate(chunks, start=1):
                payload = {
                    "chunk_id": f"{page.category}/{slugify(page.title)}#{index}",
                    "page_id": f"{page.category}/{slugify(page.title)}",
                    "title": page.title,
                    "category": page.category,
                    "source_url": page.source_url,
                    "headings": ["Summary", "Key Facts"],
                    "text": chunk,
                    "facts": page.fields,
                    "tags": [page.category, *page.aliases[:3]],
                }
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def split_chunks(text: str, *, max_chars: int = 1400) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        if current and current_len + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def render_validation_report(findings: list[dict[str, str]], pages: list[WikiPage], local_ref: LocalReference) -> str:
    lines = [
        "# Civ6 Wiki Validation Report",
        "",
        "## 摘要",
        "",
        f"- 本地游戏数据路径: `{local_ref.root}`",
        f"- 本地游戏数据可用: `{str(local_ref.present).lower()}`",
        f"- 页面数量: {len(pages)}",
        f"- 差异数量: {len(findings)}",
        "",
        "## 差异记录",
        "",
    ]
    if not findings:
        lines.append("- 未发现 Wiki 字段与本机游戏数据的明确冲突。")
    else:
        for finding in findings:
            lines.append(
                "- "
                f"Page: {finding['page']}; Field: {finding['field']}; "
                f"Wiki: `{finding['wiki_value']}`; Local: `{finding['local_value']}`; "
                f"File: `{finding['local_file']}`"
            )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 本报告只记录事实字段校验结果，不把差异静默写回页面。",
            "- 未匹配到本机实体的页面不会被当作冲突，页面内会保留 validation note。",
            "- 剧本和 scenario-specific 内容按构建规则排除。",
            "",
        ]
    )
    return "\n".join(lines)


def render_index(pages: list[WikiPage], manifest: dict[str, Any]) -> str:
    categories: dict[str, list[WikiPage]] = {}
    for page in pages:
        categories.setdefault(page.category, []).append(page)
    lines = [
        "# Civ6 Wiki Knowledge Base",
        "",
        "English factual Markdown pages for model retrieval. This knowledge base is generated from Civilization Wiki/Fandom and checked against local Civilization VI game data when available.",
        "",
        "## Build",
        "",
        f"- Generated at: {manifest['generated_at']}",
        f"- Pages: {manifest['counts']['pages']}",
        f"- Validation findings: {manifest['counts']['validation_findings']}",
        "",
        "## Categories",
        "",
    ]
    for category in sorted(categories):
        lines.append(f"- [{category}](pages/{category}/index.md): {len(categories[category])} pages")
    lines.append("")
    return "\n".join(lines)


def write_category_indexes(out_dir: Path, pages: list[WikiPage]) -> None:
    categories: dict[str, list[WikiPage]] = {}
    for page in pages:
        categories.setdefault(page.category, []).append(page)
    for category, category_pages in categories.items():
        target = out_dir / "pages" / category / "index.md"
        lines = [f"# {category}", ""]
        for page in sorted(category_pages, key=lambda item: item.title):
            rel = Path(page.path).name
            lines.append(f"- [{page.title}]({rel})")
        lines.append("")
        target.write_text("\n".join(lines), encoding="utf-8")


def safe_publish(source: Path, destination: Path) -> None:
    resolved = destination.resolve()
    expected_parent = (WORKSPACE_ROOT / "plugin" / "assets" / "codex_hl" / "knowledge").resolve()
    if expected_parent not in resolved.parents or resolved.name != "civ6-wiki":
        raise ValueError(f"Refusing to publish outside plugin knowledge base: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def build_knowledge_base(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out)
    plugin_kb = Path(args.plugin_kb)
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    client = FandomClient(rate_limit_seconds=args.rate_limit_seconds, max_retries=args.max_retries)
    candidates = collect_source_candidates(client, sample_only=args.sample_only, no_network=args.no_network)
    source_map = {candidate.title: candidate.category for candidate in candidates}
    page_sources = load_page_sources(client, candidates, no_network=args.no_network, cache_dir=cache_dir)

    pages: list[WikiPage] = []
    excluded_count = 0
    for title, (wikitext, wiki_categories) in sorted(page_sources.items()):
        source_category = source_map.get(title, SAMPLE_PAGES.get(title, "core-mechanics"))
        page = build_page(title, source_category, wikitext, wiki_categories)
        if page is None:
            excluded_count += 1
            continue
        pages.append(page)

    local_ref = load_local_reference(Path(args.game_root))
    findings = validate_pages(pages, local_ref)
    manifest = write_outputs(
        out_dir,
        pages,
        findings,
        local_ref=local_ref,
        source_count=len(candidates),
        excluded_count=excluded_count,
        sample_only=args.sample_only,
        no_network=args.no_network,
    )
    if args.publish_plugin_kb:
        safe_publish(out_dir, plugin_kb)
        manifest["published_plugin_kb"] = str(plugin_kb)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="staging output directory")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="local Fandom page cache directory")
    parser.add_argument("--plugin-kb", default=str(DEFAULT_PLUGIN_KB), help="plugin knowledge-base directory")
    parser.add_argument("--publish-plugin-kb", action="store_true", help="replace plugin KB with the staged build")
    parser.add_argument("--game-root", default=str(DEFAULT_GAME_ROOT), help="local Civilization VI install root")
    parser.add_argument("--rate-limit-seconds", type=float, default=0.5, help="minimum delay between Fandom API calls")
    parser.add_argument("--max-retries", type=int, default=4, help="Fandom API retries per request")
    parser.add_argument("--sample-only", action="store_true", help="build only representative acceptance pages")
    parser.add_argument("--no-network", action="store_true", help="use built-in fixture pages instead of Fandom API")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        manifest = build_knowledge_base(args)
    except Exception as exc:  # pragma: no cover - CLI error surface
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
