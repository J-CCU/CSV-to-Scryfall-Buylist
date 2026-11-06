#!/usr/bin/env python3
"""Collection Pricer - Magic, Pokemon, Yu-Gi-Oh!, One Piece, Riftbound.

One-file build of the cardpricer package (made by make_single_file.py; edit
the package, not this file). Run:
    Windows:  py card_pricer.py
    Mac:      python3 card_pricer.py
Needs: pip install requests openpyxl
"""



# ======================================================================
# cardpricer/text.py
# ======================================================================

import re
import unicodedata

# Known set aliases remain user-facing conveniences. Card treatments/variants are
# intentionally NOT maintained as a hard-coded list. The matcher learns available
# treatment metadata directly from Scryfall bulk data (frame_effects, promo_types,
# finishes, frame, and related flags), so new treatments can be recognized without
# another program update.



def norm(s):
    s = s or ""
    s = (s.replace("\u2019", "'").replace("\u2018", "'")
           .replace("\u2013", "-").replace("\u2014", "-")
           .replace("\u00a0", " "))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.strip().lower())

def compact(s):
    return re.sub(r"[^a-z0-9]", "", norm(s))

def collector_number_equal(a, b):
    """Compare collector numbers without treating leading zeros as meaningful."""
    a = norm(a)
    b = norm(b)
    if a == b:
        return True
    if re.fullmatch(r"0*\d+", a or "") and re.fullmatch(r"0*\d+", b or ""):
        return str(int(a)) == str(int(b))
    return False

def money(v):
    try:
        if v in (None, ""):
            return None
        return float(str(v).replace("$", "").replace(",", "").strip())
    except Exception:
        return None

def money_text(v):
    return "" if v is None else f"${v:,.2f}"

def unique(seq):
    out = []
    seen = set()
    for x in seq:
        k = norm(x)
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out

def split_leading_quantity(text):
    """Extract a clearly leading quantity without mistaking collector numbers."""
    text=(text or "").strip()
    if not text:
        return text, None
    if re.match(r"^(?:#|no\.?\s*|collector(?:\s+number|\s+no\.?)?\s*)\d+", text, re.I):
        return text, None
    m=re.match(r"^(\d+)\s*([xX]\s+|\s+)(.+)$", text)
    if not m:
        return text, None
    qty=int(m.group(1))
    # "151 Booster Bundle", "2002 Collectors Tin": a bare number over 99 is
    # part of the name; a real count that large is written "120x".
    if qty > 99 and "x" not in m.group(2).lower():
        return text, None
    return (m.group(3).strip(), qty) if qty >= 1 else (text, None)

def _is_number_only(value):
    return bool(re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value or ""))

def _header_index(headers, aliases):
    normalized = {norm(h): i for i, h in enumerate(headers)}
    for alias in aliases:
        if norm(alias) in normalized:
            return normalized[norm(alias)]
    return None

def parse_qty(v):
    try:
        return max(1, int(float(v)))
    except Exception:
        return 1

def _name_words(text):
    """Words for whole-word name comparison; apostrophes are dropped so
    "Mishras" equals "Mishra's" and "//" in split cards is ignored."""
    return re.findall(r"[a-z0-9]+", norm(text).replace("'", ""))

def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


# ======================================================================
# cardpricer/paths.py
# ======================================================================

import os
import sys
from pathlib import Path

# ------------------------------------------------------------
# Persistent application data directory
# ------------------------------------------------------------
# IMPORTANT FOR PYINSTALLER:
# A --onefile executable is unpacked into a temporary directory each time it
# starts.  Never store the Scryfall bulk file, metadata, index, or search cache
# beside __file__ when running from a bundled executable, or the cache can
# disappear on every launch and the program will repeatedly rebuild/download
# the database.
#
# Keep all mutable database files in the user's persistent application-data
# directory instead.  This makes normal launches fast: metadata check -> load
# existing index -> self-test.
# ------------------------------------------------------------
def get_data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        root = Path(base) / "MTGCollectionBuyer"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "MTGCollectionBuyer"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = (Path(base) if base else Path.home() / ".local" / "share") / "MTGCollectionBuyer"
    root.mkdir(parents=True, exist_ok=True)
    return root

DATA_DIR = get_data_dir()

BUNDLE_DIR = Path(__file__).resolve().parent

SETTINGS = DATA_DIR / "pricer_settings.json"

UA = {"User-Agent": "MTGCollectionBuyer/2.0 (personal collection pricing)"}


# ======================================================================
# cardpricer/conditions.py
# ======================================================================

import re


# ------------------------------------------------------------
# Card condition vocabulary
# ------------------------------------------------------------
# Every condition is normalized to the TCGplayer scale: NM, LP, MP, HP, DMG.
# Other marketplace scales are mapped onto it:
#   Card Kingdom:      NM / EX / VG / G           -> NM / LP / MP / HP
#   Legacy US grading: M / NM / SP / PL           -> NM / NM / LP / MP
#   Cardmarket:        MT / NM / EX / GD / PL / PO -> NM / NM / LP / HP / MP / DMG
# Where scales disagree (Cardmarket "LP" is roughly TCGplayer MP), the US
# meaning wins because prices come from TCGplayer via Scryfall.
CONDITION_ORDER = ("NM", "LP", "MP", "HP", "DMG")

CONDITION_ALIASES = {
    "near mint": "NM", "nm": "NM", "mint": "NM", "mt": "NM", "gem mint": "NM",
    "near mint or better": "NM", "nm/m": "NM", "nm-m": "NM",
    "lightly played": "LP", "light played": "LP", "lp": "LP",
    "slightly played": "LP", "sp": "LP", "excellent": "LP", "ex": "LP",
    "moderately played": "MP", "mp": "MP", "played": "MP", "pl": "MP",
    "very good": "MP", "vg": "MP",
    "heavily played": "HP", "heavy played": "HP", "hp": "HP", "good": "HP", "gd": "HP",
    "damaged": "DMG", "dmg": "DMG", "dm": "DMG", "poor": "DMG", "po": "DMG",
}

# Single letters are only trusted in an explicit condition column.
CONDITION_SHORT_ALIASES = {"m": "NM", "g": "HP", "d": "DMG"}

# Words that can appear in a card title, so they are only treated as a
# condition when they trail the title or sit in parentheses/brackets.
CONDITION_TRAILING_ONLY = {"mint", "mt", "excellent", "good", "very good", "played",
                           "poor", "po", "pl", "gd", "dm", "gem mint"}

_COND_ALT = "|".join(sorted((re.escape(k).replace(r"\ ", r"\s+") for k in CONDITION_ALIASES),
                            key=len, reverse=True))

_COND_TITLE_RE = re.compile(
    r"(?<![\w'])((?:" + _COND_ALT + r")(?:\s*[/-]\s*(?:" + _COND_ALT + r"))?)"
    r"(?:\+|-(?!\s*\d))?(?:\s+condition)?(?![\w'])",
    re.I,
)

_COND_TRAILER_RE = re.compile(r"^(?:\s|[)\]|,;*–—-]|\([^()]*\))*$")

def normalize_condition(value, allow_short=True):
    """Map any condition spelling to NM/LP/MP/HP/DMG, or a range like "LP/MP".

    Returns None when the value is not a recognizable condition.
    """
    # Exports write "near_mint" (ManaBox) or "Good (Lightly Played)" (Deckbox,
    # where the bracketed text is the TCGplayer grade); try that text first.
    inner = re.search(r"\(([^()]+)\)", value or "")
    if inner and not re.fullmatch(r"\s*\(([^()]+)\)\s*", value or ""):
        found = normalize_condition(inner.group(1), allow_short)
        if found:
            return found
    n = re.sub(r"\s+", " ", norm(value).replace("_", " ").strip(" .*()[]"))
    if not n:
        return None
    aliases = dict(CONDITION_ALIASES)
    if allow_short:
        aliases.update(CONDITION_SHORT_ALIASES)
    if n in aliases:
        return aliases[n]
    n = n.rstrip("+-").strip()
    if n in aliases:
        return aliases[n]
    parts = [p.strip().rstrip("+-").strip() for p in re.split(r"\s*(?:/|-|\bto\b)\s*", n)]
    mapped = [aliases.get(p) for p in parts if p]
    if not mapped or None in mapped:
        return None
    found = sorted(set(mapped), key=CONDITION_ORDER.index)
    return found[0] if len(found) == 1 else f"{found[0]}/{found[-1]}"

def extract_title_condition(text, name_words=()):
    """Find a condition written in a card title and remove it from the title.

    Returns (condition or "", cleaned text). If several conditions appear,
    the last one wins. Words that can be part of a card name (Good, Mint,
    Played, ...) only count when they trail the title or are bracketed.
    name_words are words a game uses in card names ("ex" in "Charizard ex",
    "SP" in One Piece) and are never read as a condition.
    """
    found = ""
    spans = []
    for m in _COND_TITLE_RE.finditer(text or ""):
        phrase = m.group(1)
        words = {norm(p) for p in re.split(r"\s*[/-]\s*", phrase)}
        if words & set(name_words):
            continue
        if words & CONDITION_TRAILING_ONLY:
            bracketed = (re.search(r"[(\[]\s*$", text[:m.start()])
                         and re.match(r"\s*[)\]]", text[m.end():]))
            if not bracketed and not _COND_TRAILER_RE.match(text[m.end():]):
                continue
        cond = normalize_condition(phrase, allow_short=False)
        if not cond:
            continue
        found = cond
        spans.append(m.span())
    cleaned = text or ""
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    if spans:
        cleaned = re.sub(r"[(\[]\s*[)\]]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;|*-")
    return found, cleaned

def _looks_like_condition(value):
    return normalize_condition(value, allow_short=False) is not None


# ======================================================================
# cardpricer/clues.py
# ======================================================================

import re

# Language words/codes sellers put in titles. Multi-word entries come first
# so "Simplified Chinese" wins over "Chinese".
LANGUAGE_ALIASES = {
    "SIMPLIFIED CHINESE": "zhs", "TRADITIONAL CHINESE": "zht",
    "JAPANESE": "ja", "GERMAN": "de", "FRENCH": "fr", "ITALIAN": "it",
    "SPANISH": "es", "PORTUGUESE": "pt", "RUSSIAN": "ru", "KOREAN": "ko",
    "CHINESE": "zhs", "ENGLISH": "en", "ENG": "en",
    "JPN": "ja", "JP": "ja", "JAP": "ja", "TCH": "zht", "CHT": "zht",
    "SCH": "zhs", "CHS": "zhs", "ITL": "it", "ITA": "it", "GRM": "de",
    "GER": "de", "FRN": "fr", "FRE": "fr", "SPN": "es", "SPA": "es",
    "RUS": "ru", "KOR": "ko", "POR": "pt",
}

LANGUAGE_CODES = {"en", "ja", "de", "fr", "it", "es", "pt", "ru", "ko", "zhs", "zht", "zh", "ph"}

# Anything outside Latin, punctuation and common symbol blocks.
NON_LATIN_RE = re.compile(r"[^\x00-ɏḀ-ỿ -⅟←-⏿☀-➿]")

# Graders and grades: "PSA 10", "BGS 9.5", "CGC Gem Mint 10", "Beckett 9".
GRADED_RE = re.compile(
    r"\b(PSA|BGS|CGC|SGC|TAG|BECKETT)\s*(?:gem\s*mint\s*|mint\s*|pristine\s*)?(\d{1,2}(?:\.\d+)?)(?![\d.])", re.I)

# Sealed product. Bare "box"/"deck"/"pack" are left out because card names
# use them (Pandora's Box, Pack Rat, Deck of Fate).
SEALED_RE = re.compile(
    r"\bsealed\b|\bunopened\b|\bfactory\s+sealed\b|\bshrink\s*wrap(?:ped)?\b"
    r"|\bbooster\s+(?:box|pack|packs|display|case|brick|bundle)\b"
    r"|\b(?:collector|set|draft|play|jumpstart|vip|premium)\s+boosters?(?:\s+(?:box|pack|display|case))?\b"
    r"|\b(?:bundle|fat\s+pack|gift\s+bundle|gift\s+box|prerelease\s+(?:kit|pack)|starter\s+kit"
    r"|(?:commander|starter|theme|planeswalker|intro|challenger|duel|event|welcome|brawl)\s+decks?"
    r"|precon(?:structed)?(?:\s+deck)?|tournament\s+pack|deck\s*builder'?s\s+toolkit|premium\s+deck\s+series"
    r"|secret\s+lair\s+(?:drop|bundle))\b",
    re.I,
)

GRADED_WORD_RE = re.compile(r"\bgraded\b|\bslab(?:bed)?\b", re.I)

def language_code(value):
    """Map a language cell/word to a Scryfall language code, or None."""
    v = (value or "").strip()
    if not v:
        return None
    if v.upper() in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[v.upper()]
    if v.lower() in LANGUAGE_CODES:
        return v.lower()
    return None


# ======================================================================
# cardpricer/pricing.py
# ======================================================================

SPECIAL_RULE_LABELS = {"all": "All cards", "abu": "Alpha/Beta/Unlimited", "foil": "Foil / etched"}

DEFAULT_SPECIAL_RULES = {
    "all": {"NM": 100, "LP": 85, "MP": 70, "HP": 50, "DMG": 25},
    "abu": {"NM": 100, "LP": 80, "MP": 60, "HP": 40, "DMG": 20},
    "foil": {"NM": 100, "LP": 75, "MP": 50, "HP": 30, "DMG": 15},
}

def condition_value_percent(condition_pcts, condition, special_ratios=()):
    """What a copy in this condition is worth, as a % of the NM price.

    A blank condition cell counts as 100%. A range such as LP/MP uses the
    average of its two ends. Each special ratio set (old set, foil) caps the
    value; the lowest wins.
    """
    parts = [p for p in (condition or "").split("/") if p in CONDITION_ORDER]
    if not parts:
        return 100.0

    def rate(cond):
        value = condition_pcts.get(cond) if condition_pcts.get(cond) is not None else 100.0
        for ratios in special_ratios:
            if ratios.get(cond) is not None:
                value = min(value, ratios[cond])
        return value

    vals = [rate(p) for p in parts]
    return sum(vals) / len(vals)

def normalize_special_rules(rules):
    """Parse {"abu": {"LP": "80", ...}, ...}; blank or invalid cells are skipped."""
    clean = {}
    for key in SPECIAL_RULE_LABELS:
        ratios = {}
        for cond, value in ((rules or {}).get(key) or {}).items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if cond in CONDITION_ORDER and value >= 0:
                ratios[cond] = value
        if ratios:
            clean[key] = ratios
    return clean

def normalize_buy_tiers(tiers):
    """Normalize editable price bands.

    Each tier is (low, high, percent) or (low, high, percent, condition_pcts),
    where condition_pcts maps NM/LP/MP/HP/DMG to the % of NM value a copy in
    that condition is worth (blank = 100%). high=None means no upper limit.
    Percentages are written as 50 for 50%.
    """
    clean = []
    for tier in tiers:
        low, high, pct = tier[:3]
        raw_conds = tier[3] if len(tier) > 3 else {}
        try:
            low = float(low)
            high = None if high in (None, "", "inf", "infinity") else float(high)
            pct = float(pct)
        except Exception:
            continue
        if low < 0 or (high is not None and high <= low) or pct < 0:
            continue
        cond_pcts = {}
        for cond in CONDITION_ORDER:
            value = (raw_conds or {}).get(cond)
            if value in (None, ""):
                continue
            try:
                value = float(value)
            except Exception:
                continue
            if value >= 0:
                cond_pcts[cond] = value
        clean.append((low, high, pct, cond_pcts))
    clean.sort(key=lambda x: x[0])
    return clean

def tier_for_price(price, tiers):
    """Return the (low, high, buy %, condition %) tier containing price."""
    if price is None:
        return None
    for tier in normalize_buy_tiers(tiers):
        low, high = tier[0], tier[1]
        if price >= low and (high is None or price < high):
            return tier
    return None

def price_offer(nm_price, tiers, condition=None, special_ratios=(), condition_pcts=None):
    """Condition first, then the buy % range.

    1. NM price x condition % (NM 100, MP 70, ...) = condition value.
    2. The condition value's range sets the Buy %.
    E.g. $100 NM in MP at 70% -> $70 -> the $50-80 range's 50% -> $35.
    condition_pcts is the flat "All cards" row; without it, the condition
    columns of the NM price's range are used. Returns (condition %,
    condition value, buy %, offer); None parts when no range covers a price.
    """
    if nm_price is None:
        return None, None, None, None
    if condition_pcts is None:
        nm_tier = tier_for_price(nm_price, tiers)
        if nm_tier is None:
            return None, None, None, None
        condition_pcts = nm_tier[3]
    cond_pct = condition_value_percent(condition_pcts, condition, special_ratios)
    value = nm_price * cond_pct / 100.0
    value_tier = tier_for_price(value, tiers)
    if value_tier is None:
        return cond_pct, value, None, None
    return cond_pct, value, value_tier[2], value * value_tier[2] / 100.0

# What a played copy is worth relative to NM, by NM price. LP/MP/HP follow
# Card Kingdom's published buylist schedule (EX/VG/G as a share of the NM
# buy price: <$25 80/70/50, $25-99.99 85/75/65, $100+ 90/80/70). Card
# Kingdom rejects below-Good cards, so DMG is set at roughly half of HP.
CONDITION_MARKET_RATIOS = [
    (0, {"NM": 1.00, "LP": 0.80, "MP": 0.70, "HP": 0.50, "DMG": 0.25}),
    (25, {"NM": 1.00, "LP": 0.85, "MP": 0.75, "HP": 0.65, "DMG": 0.30}),
    (100, {"NM": 1.00, "LP": 0.90, "MP": 0.80, "HP": 0.70, "DMG": 0.35}),
]

def market_condition_pcts(low):
    """Default condition values (% of NM) for a tier starting at NM price low."""
    try:
        low = float(low or 0)
    except (TypeError, ValueError):
        return {}
    ratios = [r for threshold, r in CONDITION_MARKET_RATIOS if low >= threshold][-1]
    return {c: f"{round(100 * ratios[c], 1):g}" for c in CONDITION_ORDER}

DEFAULT_BUY_TIERS = [(0, 25, 50), (25, 100, 55), (100, 500, 60), (500, 1000, 65), (1000, None, 70)]
# Sealed product has no condition step: market price x the range's Buy %.
DEFAULT_SEALED_TIERS = [(0, 50, 55), (50, 200, 65), (200, None, 70)]

# 3: per-range condition columns held % of NM value instead of a final buy %.
# 4: one flat "All cards" condition row; price ranges hold only Buy %.
SETTINGS_VERSION = 4

def migrate_settings(settings):
    """Bring saved settings up to version 4, keeping what the user entered."""
    version = settings.get("version", 1)
    tiers = settings.get("tiers") or []
    if version >= SETTINGS_VERSION or not tiers:
        return settings
    tiers = migrate_tier_conditions(tiers, version)
    rules = dict(settings.get("special_rules") or {})
    if "all" not in rules:
        # The lowest range holds most cards; its condition values become the
        # flat row unless they were never changed from the old defaults.
        first = tiers[0]
        conds = first[3] if len(first) > 3 else {}
        defaults = market_condition_pcts(first[0])
        changed = any(str(conds.get(c, "")).strip() != defaults.get(c) for c in CONDITION_ORDER)
        rules["all"] = ({c: conds.get(c, "") for c in CONDITION_ORDER} if changed
                        else dict(DEFAULT_SPECIAL_RULES["all"]))
    settings["special_rules"] = rules
    settings["tiers"] = [list(t[:3]) for t in tiers]
    settings["version"] = SETTINGS_VERSION
    return settings

def migrate_tier_conditions(tiers, version):
    """Bring saved price ranges up to the condition-value format.

    Never-filled condition cells get market defaults. Cells the user filled
    in under version 1-2 were final buy %s; they are converted to the same
    share of that range's NM rate, so the user's relative discounts survive.
    """
    out = []
    for t in tiers:
        if len(t) < 3:
            continue
        conds = dict(t[3]) if len(t) > 3 and t[3] else {}
        if version < 3:
            if not any(str(v).strip() for v in conds.values()):
                conds = market_condition_pcts(t[0])
            else:
                try:
                    nm = float(conds.get("NM") or t[2])
                except (TypeError, ValueError):
                    nm = 0
                conds = {c: (f"{round(float(v) / nm * 100, 1):g}" if str(v).strip() and nm else "")
                         for c, v in conds.items()}
        out.append(list(t[:3]) + [conds])
    return out


# ======================================================================
# cardpricer/sources/tcgcsv.py
# ======================================================================

import gzip
import json
import pickle
import re
import time

import requests


BASE_URL = "https://tcgcsv.com"
TCGCSV_UA = {"User-Agent": "MTGCollectionBuyer/3.0 (collection pricing; daily sync)"}
REQUEST_DELAY = 0.15
TCGCSV_DIR = DATA_DIR / "tcgcsv"
CATALOG_INDEX_VERSION = 1

GAMES = {
    "magic": {"category": 1, "label": "Magic: The Gathering"},
    "pokemon": {"category": 3, "label": "Pokémon"},
    "yugioh": {"category": 2, "label": "Yu-Gi-Oh!"},
    "onepiece": {"category": 68, "label": "One Piece"},
    "riftbound": {"category": 89, "label": "Riftbound"},
}


def _get_json(session, url):
    time.sleep(REQUEST_DELAY)
    r = session.get(url, headers=TCGCSV_UA, timeout=60)
    if r.status_code == 404:
        return {"results": []}  # TCGplayer returns 404 for empty groups
    r.raise_for_status()
    return r.json()


def choose_price(price_row):
    """Return (price, basis) for one TCGCSV price row.

    Market price first. Very expensive cards often have no market price
    (Alpha Black Lotus); then the lowest listing is used and marked so the
    row can be flagged for review.
    """
    if not price_row:
        return None, ""
    if price_row.get("marketPrice") is not None:
        return float(price_row["marketPrice"]), "TCGplayer Market"
    if price_row.get("lowPrice") is not None:
        return float(price_row["lowPrice"]), "TCGplayer Low (no market price)"
    return None, ""


class Catalog:
    """One game's products with prices, plus lookup indexes."""

    def __init__(self, game, products, groups):
        self.game = game
        self.products = products          # productId -> product dict
        self.groups = groups              # groupId -> group dict
        self.by_name = {}                 # norm(base name) -> [product]
        self.by_number = {}               # norm(number) -> [product]
        for p in products.values():
            self.by_name.setdefault(norm(p["base_name"]), []).append(p)
            if p["number"]:
                self.by_number.setdefault(norm(p["number"]), []).append(p)

    def get(self, product_id):
        return self.products.get(int(product_id)) if product_id else None


def _ext(product, key):
    for e in product.get("extendedData") or []:
        if e.get("name") == key:
            return (e.get("value") or "").strip()
    return ""


def base_product_name(name):
    """Card name without the trailing number TCGplayer adds to some games
    ("Pikachu - 173/165" -> "Pikachu")."""
    return re.sub(r"\s+-\s+[A-Za-z0-9]*\d[A-Za-z0-9/\-]*\s*$", "", name or "").strip()


def build_catalog(game, raw):
    """Turn cached raw TCGCSV JSON into a Catalog."""
    groups = {g["groupId"]: g for g in raw["groups"]}
    prices = {}
    for gid, rows in raw["prices"].items():
        for row in rows:
            prices.setdefault(row["productId"], {})[row.get("subTypeName") or "Normal"] = row
    products = {}
    for gid, rows in raw["products"].items():
        group = groups.get(int(gid), {})
        for p in rows:
            number = _ext(p, "Number")
            rarity = _ext(p, "Rarity")
            products[p["productId"]] = {
                "id": p["productId"],
                "game": game,
                "name": p.get("name", ""),
                "base_name": base_product_name(p.get("name", "")),
                "clean_name": p.get("cleanName", ""),
                "group_id": int(gid),
                "group_name": group.get("name", ""),
                "group_abbr": group.get("abbreviation") or "",
                "released": (group.get("publishedOn") or "")[:10],
                "number": number,
                "rarity": rarity,
                # Sealed product has neither a card number nor a rarity.
                "sealed": not number and not rarity,
                "url": p.get("url", ""),
                "image": p.get("imageUrl", ""),
                "ext": {e.get("name"): (e.get("value") or "") for e in p.get("extendedData") or []
                        if e.get("name") in ("Number", "Rarity", "Card Type", "Attribute", "Color", "Monster Type",
                                             "SubType", "Description")},
                "prices": prices.get(p["productId"], {}),
            }
    return Catalog(game, products, groups)


class TCGCSV:
    def __init__(self, log, session=None):
        self.log = log
        self.session = session or requests.Session()
        TCGCSV_DIR.mkdir(parents=True, exist_ok=True)
        self.catalogs = {}

    # ---- sync -----------------------------------------------------------
    def remote_stamp(self):
        time.sleep(REQUEST_DELAY)
        r = self.session.get(f"{BASE_URL}/last-updated.txt", headers=TCGCSV_UA, timeout=30)
        r.raise_for_status()
        return r.text.strip()

    def _raw_path(self, game):
        return TCGCSV_DIR / f"{game}.json.gz"

    def _load_raw(self, game):
        path = self._raw_path(game)
        if not path.exists():
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_raw(self, game, raw):
        tmp = self._raw_path(game).with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(raw, f)
        tmp.replace(self._raw_path(game))

    def sync(self, games, progress=None):
        """Download the chosen games if TCGCSV has newer data. Returns True
        if anything changed."""
        stamp = self.remote_stamp()
        changed = False
        for game in games:
            category = GAMES[game]["category"]
            raw = self._load_raw(game) or {}
            if raw.get("stamp") == stamp and raw.get("complete"):
                self.log(f"TCGCSV {GAMES[game]['label']}: already current ({stamp}).")
                continue
            self.log(f"TCGCSV {GAMES[game]['label']}: syncing data from {stamp}...")
            groups = _get_json(self.session, f"{BASE_URL}/tcgplayer/{category}/groups")["results"]
            old_groups = {g["groupId"]: g for g in raw.get("groups", [])}
            products = raw.get("products", {})
            prices = raw.get("prices", {}) if raw.get("stamp") == stamp else {}
            done_prices = set(raw.get("done_prices", [])) if raw.get("stamp") == stamp else set()
            raw = {"stamp": stamp, "complete": False, "groups": groups, "products": products,
                   "prices": prices, "done_prices": sorted(done_prices)}
            for i, g in enumerate(groups, 1):
                gid = str(g["groupId"])
                old = old_groups.get(g["groupId"])
                if gid not in products or not old or old.get("modifiedOn") != g.get("modifiedOn"):
                    products[gid] = _get_json(self.session, f"{BASE_URL}/tcgplayer/{category}/{gid}/products")["results"]
                if gid not in done_prices:
                    prices[gid] = _get_json(self.session, f"{BASE_URL}/tcgplayer/{category}/{gid}/prices")["results"]
                    done_prices.add(gid)
                if i % 25 == 0 or i == len(groups):
                    raw["done_prices"] = sorted(done_prices)
                    self._save_raw(game, raw)  # checkpoint so an interrupted sync resumes
                    self.log(f"  {i}/{len(groups)} sets")
                if progress:
                    progress(i, len(groups))
            live = {str(g["groupId"]) for g in groups}
            raw["products"] = {k: v for k, v in products.items() if k in live}
            raw["prices"] = {k: v for k, v in prices.items() if k in live}
            raw["complete"] = True
            self._save_raw(game, raw)
            self._index_path(game).unlink(missing_ok=True)
            self.catalogs.pop(game, None)
            changed = True
        return changed

    # ---- catalogs -------------------------------------------------------
    def _index_path(self, game):
        return TCGCSV_DIR / f"{game}_index.pkl"

    def has_data(self, game):
        raw = self._load_raw(game)
        return bool(raw and raw.get("complete"))

    def catalog(self, game):
        """Load (or build and cache) one game's Catalog; None if not synced."""
        if game in self.catalogs:
            return self.catalogs[game]
        path = self._index_path(game)
        if path.exists():
            try:
                data = pickle.loads(path.read_bytes())
                if data.get("version") == CATALOG_INDEX_VERSION:
                    cat = Catalog(game, data["products"], data["groups"])
                    self.catalogs[game] = cat
                    return cat
            except Exception:
                pass
        raw = self._load_raw(game)
        if not raw or not raw.get("complete"):
            return None
        cat = build_catalog(game, raw)
        path.write_bytes(pickle.dumps({"version": CATALOG_INDEX_VERSION, "products": cat.products, "groups": cat.groups},
                                      pickle.HIGHEST_PROTOCOL))
        self.catalogs[game] = cat
        self.log(f"TCGCSV {GAMES[game]['label']}: {len(cat.products):,} products indexed.")
        return cat


# ======================================================================
# cardpricer/games/magic.py
# ======================================================================

# ============================================================
# MTG COLLECTION BUYER
# Dirty collection list -> Scryfall identification -> pricing
# ============================================================
# Important design rules:
#   * Parse the input into card-name + constraints BEFORE matching.
#   * Exact card name always outranks fuzzy matching.
#   * Finish, set, variant, and collector-number clues FILTER candidates.
#   * Multiple printings are NOT automatically ambiguous.
#   * A foil request such as "Intuition Foil" searches all Intuition
#     printings and selects the applicable foil printing.  If there is
#     exactly one foil printing, it is resolved automatically.
#   * Unknown/alias names may be resolved through Scryfall search.
#   * Fuzzy matching is a last resort, and is never allowed to override
#     strong set/finish/collector-number evidence.
#   * Graded cards are identified but are NOT assigned an ungraded price.
#   * Scryfall supplies TCGplayer price fields, but not TCGplayer
#     the program uses only Scryfall price fields and does not attempt to reproduce a separate marketplace low price.
# ============================================================

import gzip
import heapq
import json
import multiprocessing as mp
import pickle
import re
import requests
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from difflib import SequenceMatcher
from pathlib import Path


BULK_GZ = DATA_DIR / "scryfall_all_cards.jsonl.gz"

BULK_META = DATA_DIR / "bulk_metadata.json"

# Separate from the original collection_pricer.py index so the two programs
# never rebuild over each other.
INDEX = DATA_DIR / "cardpricer_scryfall_index.pkl"

SEARCH_CACHE = DATA_DIR / "scryfall_name_cache.json"

# Legacy cache migration / discovery. PyInstaller bundles are read-only and
# one-file builds unpack to temporary locations, so mutable Scryfall data must
# live in DATA_DIR. We also actively look for an existing bulk file in the
# source/app folder and copy it once instead of downloading it again.
def _legacy_candidate_dirs():
    dirs = []
    for d in (BUNDLE_DIR, Path.cwd()):
        try:
            d = d.resolve()
        except Exception:
            continue
        if d not in dirs:
            dirs.append(d)
    # For a .app, also check the directory containing the executable and its
    # parent locations where a user may have kept the database beside the app.
    try:
        exe = Path(sys.executable).resolve()
        for d in (exe.parent, exe.parent.parent, exe.parent.parent.parent):
            if d not in dirs:
                dirs.append(d)
    except Exception:
        pass
    return dirs

def migrate_legacy_cache(log=None):
    candidates = _legacy_candidate_dirs()
    bulk_names = (
        "scryfall_all_cards.jsonl.gz",
        "scryfall_all_cards.jsonl.tmp",
    )
    meta_names = ("bulk_metadata.json",)
    index_names = ("scryfall_index.pkl", "scryfall_index_v15.pkl", "scryfall_index_v14.pkl")
    search_names = ("scryfall_name_cache.json", "scryfall_name_cache_v8.json", "scryfall_name_cache_v5.json")

    def copy_first(names, dest):
        if dest.exists():
            return False
        for directory in candidates:
            for name in names:
                src = directory / name
                if src.exists() and src.is_file():
                    try:
                        import shutil
                        shutil.copy2(src, dest)
                        if log:
                            log(f"Migrated existing Scryfall cache: {src} -> {dest}")
                        return True
                    except Exception as e:
                        if log:
                            log(f"Could not migrate {src}: {e}")
        return False

    copy_first(bulk_names, BULK_GZ)
    copy_first(meta_names, BULK_META)
    copy_first(index_names, INDEX)
    copy_first(search_names, SEARCH_CACHE)

migrate_legacy_cache()

BULK_API = "https://api.scryfall.com/bulk-data"

INDEX_VERSION = 18  # 18: TCGplayer product ids for TCGCSV prices

SELF_TEST_NAMES = (
    "Mishra's Workshop",
    "Grim Monolith",
    "Black Lotus",
    "Primeval Titan",
)

# Condition values: what a copy in each condition is worth as a % of the NM
# price. "All cards" applies to everything (LP/MP/HP from Card Kingdom's
# buylist: EX 80-90, VG 70-80, G 50-70; DMG about half of HP). Old-set and
# foil cards lose more value to wear (Card Kingdom: Alpha/Beta/Unlimited
# 80/60/40, foils 75/50/30); for those, the lower value is used.
ABU_SET_CODES = {"lea", "leb", "2ed"}

# User-facing set aliases.  The matcher also accepts the real Scryfall set name.
SET_ALIASES = {
    "unlim": ["unlimited edition"],
    "unlimited": ["unlimited edition"],
    "7th ed": ["seventh edition"],
    "7th edition": ["seventh edition"],
    "tempest": ["tempest"],
    "onslaught": ["onslaught"],
    "revised": ["revised edition"],
    "mm": ["modern masters"],
    "lorwyn": ["lorwyn"],
    "eventide": ["eventide"],
    "shadowmoor": ["shadowmoor"],
    "morningtide": ["morningtide"],
    "urza's destiny": ["urza's destiny"],
    "urza's saga": ["urza's saga"],
    "urza's legacy": ["urza's legacy"],
    "urza's legacy0": ["urza's legacy"],
    "urea's legacy0": ["urza's legacy"],
    "urea's legacy": ["urza's legacy"],
    "arabian nights": ["arabian nights"],
    "antiquities": ["antiquities"],
    "the dark": ["the dark"],
    "fallen empires": ["fallen empires"],
    "homelands": ["homelands"],
    "mirage": ["mirage"],
    "visions": ["visions"],
    "weatherlight": ["weatherlight"],
    "stronghold": ["stronghold"],
    "exodus": ["exodus"],
    "mercadian masques": ["mercadian masques"],
    "nemesis": ["nemesis"],
    "prophecy": ["prophecy"],
    "legends": ["legends"],
    "battle royale": ["battle royale"],
    "lorwyn eclipsed": ["lorwyn eclipsed"],
    "wpn promo": ["magic premier shop", "world championship decks", "magic player rewards"],
    "promo": ["promo"],
    "from the vault": ["from the vault"],
    "mm1": ["modern masters"],
    "utm": ["ultimate masters"],
    "lor": ["lorwyn"],
    "btb": ["battlebond"],
    "legi": ["legends"],
    "cok": ["champions of kamigawa"],
    "cml": ["commander legends"],
    "apo": ["apocalypse"],
    "evt": ["eventide"],
    "shd": ["shadowmoor"],
    "pst": ["planeshift"],
    "cld": ["kaladesh"],
    "des": ["dissension"],
    "mcm": ["commander masters"],
    "icm": ["iconic masters"],
    "thr": ["theros"],
    "wlw": ["worldwake"],
    "pro": ["prophecy"],
    "tbd": ["theros beyond death"],
    "jug": ["judgment"],
    "sco": ["scourge"],
    "ali": ["alliances"],
    "p3k": ["portal three kingdoms"],
    "wea": ["weatherlight"],
    "mm2": ["modern masters 2015"],
    "m25": ["masters 25"],
    "2xm": ["double masters"],
    "zrn": ["zendikar rising"],
    "ixa": ["ixalan"],
    "ori": ["magic origins"],
    "emn": ["eldritch moon"],
    "kal": ["kaladesh"],
    "kld": ["kaladesh"],
    "str": ["stronghold"],
}

KNOWN_SET_PHRASES = sorted(SET_ALIASES.keys(), key=len, reverse=True)

# Phrases that are also common card-title words. These require stronger context
# than a bare substring match so a card name is not damaged during parsing.
AMBIGUOUS_SET_ALIASES = {"the dark", "promo"}

CARD_NAME_SHORTHAND = {
    "cop black": "Circle of Protection: Black",
    "cop blue": "Circle of Protection: Blue",
    "cop green": "Circle of Protection: Green",
    "cop red": "Circle of Protection: Red",
    "cop white": "Circle of Protection: White",
}

def expand_card_name_shorthand(text):
    original=text or ""
    n=norm(original)
    for short, full in CARD_NAME_SHORTHAND.items():
        if n == short:
            return full
        if n.startswith(short + " "):
            suffix=original[len(short):].strip()
            return full + (" " + suffix if suffix else "")
    return original

def special_rules_for(card, parsed, special_rules):
    """Return [(key, ratios)] for the special rules that apply to this printing."""
    keys = []
    if norm(card.get("set", "")) in ABU_SET_CODES:
        keys.append("abu")
    if effective_finish(card, parsed) in {"foil", "etched"}:
        keys.append("foil")
    rules = normalize_special_rules(special_rules)
    return [(k, rules[k]) for k in keys if k in rules]

def parse_dirty_title(raw):
    """Parse dirty collection text while preserving generic treatment clues.

    Variant/treatment names are deliberately metadata-driven. We keep explicit
    parenthetical annotations and generic "X foil" phrases as clues, then let
    the Scryfall database decide whether those clues actually describe a
    printing. This avoids a hard-coded list that becomes stale when Scryfall
    adds new treatments.
    """
    s = (raw or "").strip()
    work = expand_card_name_shorthand(s).replace("\u2019", "'").replace("\u2018", "'")

    sealed = bool(SEALED_RE.search(work))
    set_product = bool(re.search(r"^\s*(?:complete\s+)?set\b|\bfactory\s+set\b", work, re.I))
    signed = bool(re.search(r"(?:^|[\s,*])signed\b", work, re.I))
    # Condition words are recorded and then removed so they never reach the
    # card-name matcher or become treatment clues.
    row_condition, work = extract_title_condition(work)

    language = ""
    language_tokens = []
    for token, lang in LANGUAGE_ALIASES.items():
        if not re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", work, re.I):
            continue
        # In seller language, "JP Alternate Art" is a printing/treatment
        # descriptor, not a request to price a Japanese-language card.
        if token in {"JP", "JPN", "JAP"} and re.search(r"\bJP\s+(?:alternate|alt)\s+art\b", work, re.I):
            continue
        if any(token in longer for longer in language_tokens):
            continue  # "CHINESE" inside an already-found "SIMPLIFIED CHINESE"
        language = lang
        language_tokens.append(token)
    # Card names are Latin script; a title in another script is a
    # foreign-language printing even without a language word.
    if not language and NON_LATIN_RE.search(work):
        language = "non-latin"

    grader_m = GRADED_RE.search(work)
    graded = bool(grader_m) or bool(GRADED_WORD_RE.search(work))
    grader = grader_m.group(1).upper() if grader_m else ""
    grade = grader_m.group(2) if grader_m else ""
    if grader == "BECKETT":
        grader = "BGS"
    serialized = bool(re.search(r"\bserial(?:ized)?\b|\bserial\s+numbered\b", work, re.I))

    # Repair a common dirty-list/OCR case where a trailing parenthetical is
    # missing its closing parenthesis. Keep the contents as an annotation clue.
    unmatched_annotation = ""
    open_pos = work.rfind("(")
    close_pos = work.rfind(")")
    if open_pos >= 0 and open_pos > close_pos:
        unmatched_annotation = work[open_pos + 1:].strip()
        work = work[:open_pos].rstrip() + (" " if work[:open_pos].strip() else "")

    # Pull parenthetical annotations before stripping them. These are often the
    # most useful printing clues: Galaxy Foil, Scrolls Silver Foil, Retro Frame,
    # Borderless Poster Foil, etc. Numeric-only annotations are handled separately.
    annotations = re.findall(r"\(([^()]*)\)", work)
    annotation_clues = []
    for a in annotations + ([unmatched_annotation] if unmatched_annotation else []):
        a = re.sub(r"\s+", " ", a.strip())
        if a and not re.fullmatch(r"\d{1,4}[A-Za-z]?", a):
            annotation_clues.append(a)

    finish = "nonfoil"
    finish_explicit = False
    if re.search(r"\b(?:etched(?:\s+foil)?|etched)\b", work, re.I):
        finish = "etched"
        finish_explicit = True
    elif re.search(r"\b(?:[A-Za-z0-9'’.-]+\s+){0,4}foil\b", work, re.I):
        finish = "foil"
        finish_explicit = True

    # Parenthetical annotations are treatment clues. Plain-text special
    # treatments are discovered later from Scryfall's own metadata vocabulary.
    treatment_phrases = list(annotation_clues)

    set_cues = []
    set_patterns = []
    for alias in KNOWN_SET_PHRASES:
        pattern = r"(?<![\w'])" + re.escape(alias) + r"(?![\w'])"
        if not re.search(pattern, work, re.I):
            continue
        # "The Dark" inside a card such as Sauron, the Dark Lord is not a set
        # clue. Ambiguous aliases are accepted when they occur at the end, after
        # a separator, or in parentheses; ordinary set aliases remain flexible.
        if alias in AMBIGUOUS_SET_ALIASES:
            strong = re.search(r"(?:[-–—,]|\(|^)\s*" + re.escape(alias) + r"\s*(?:\)|$)", work, re.I)
            if not strong:
                continue
        set_cues.append(alias)
        set_patterns.append(alias)

    collector_number = ""
    # Collector numbers are often written as "- 360" or "(7031)" even when
    # the input is not explicitly marked serialized. Preserve those numbers as
    # cross-set clues. Parenthetical text is only accepted when it is numeric.
    m = re.search(r"(?:#|[-–—]\s*)(\d{1,4}[A-Za-z]?)(?=\s*(?:\([^()]*\)\s*)*$)", work)
    if m:
        collector_number = m.group(1)
    if not collector_number:
        nums = re.findall(r"\((\d{1,4}[A-Za-z]?)\)", work)
        if nums:
            collector_number = nums[-1]

    name = work
    name = GRADED_RE.sub("", name)
    name = GRADED_WORD_RE.sub("", name)
    name = re.sub(r"\bserial(?:ized)?\b|\bserial\s+numbered\b", "", name, flags=re.I)
    name = re.sub(r"\betched(?:\s+foil)?\b", "", name, flags=re.I)
    # Remove only generic finish words here. Metadata-specific treatment words
    # are removed later after the Scryfall vocabulary is available.
    for sp in set_patterns:
        name = re.sub(r"(?<![\w'])" + re.escape(sp) + r"(?![\w'])", "", name, flags=re.I)
    if collector_number:
        # Remove a collector number even when a treatment annotation follows it.
        name = re.sub(r"(?:#|[-–—]\s*)" + re.escape(collector_number) + r"(?=\s*(?:\([^()]*\)\s*)*$)", "", name)
        name = re.sub(r"\(" + re.escape(collector_number) + r"\)", "", name)
    name = re.sub(r"\([^()]*\)", " ", name)
    for token in language_tokens:
        name = re.sub(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", " ", name, flags=re.I)
    # Remove a bare generic foil word if it survived, but keep all other words.
    name = re.sub(r"\bfoil\b", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -")

    name_variants = [name]
    parts = name.split()
    if len(parts) > 2:
        name_variants.extend([" ".join(parts[:n]) for n in range(len(parts) - 1, 1, -1)])
    for piece in re.split(r"\s+[-:]\s+", name):
        piece = piece.strip()
        if len(piece.split()) >= 2:
            name_variants.append(piece)
    name_variants = unique(name_variants)

    return {
        "raw": raw,
        "name": name,
        "name_variants": name_variants,
        "name_norm": norm(name),
        "compact": compact(name),
        "finish": finish,
        "finish_explicit": finish_explicit,
        "variant_terms": unique(annotation_clues),
        "treatment_phrases": unique(treatment_phrases),
        "set_cues": set_cues,
        "collector_number": collector_number,
        "serialized": serialized,
        "graded": graded,
        "grade": grade,
        "grader": grader,
        "language": language,
        "language_tokens": language_tokens,
        "signed": signed,
        "sealed": sealed,
        "set_product": set_product,
        "row_condition": row_condition,
    }

class ScryfallDB:
    def __init__(self, log):
        self.log = log
        self.cards = []
        self.names = {}
        self.unique_names = []
        self.metadata_terms = set()
        self.set_terms = set()
        self.cache = self.load_search_cache()

        # Runtime-only acceleration structures. These are rebuilt from the
        # persistent index after loading; they are deliberately NOT sent to
        # worker processes.
        self._fuzzy_cache = {}
        self._name_hits_cache = {}
        self._embedded_cache = {}
        self._compact_name_map = {}
        self._compact_base_name_map = {}
        self._token_name_index = {}
        self._length_name_index = {}
        self._set_vocab = {}
        self._set_lookup = {}
        self._metadata_lookup = {}
        self._known_set_codes = set()

    def _build_runtime_indexes(self):
        """Build fast in-memory indexes from the persistent Scryfall index.

        This is intentionally done once per application launch, not once per
        input row. In particular, set vocabulary is cached here so metadata
        enrichment never scans 542k cards for every card in the CSV.
        """
        self._fuzzy_cache.clear()
        self._name_hits_cache.clear()
        self._embedded_cache.clear()
        self._compact_name_map = {}
        self._compact_base_name_map = {}
        self._token_name_index = {}
        self._length_name_index = {}
        self._set_vocab = {}
        self._set_lookup = {}
        self._metadata_lookup = {}
        self._known_set_codes = set()

        for c in self.cards:
            sn = norm(c.get("set_name", ""))
            sc = norm(c.get("set", ""))
            if sn:
                self._set_vocab[sn] = sn
                self._set_lookup.setdefault(sn, sn)
                self._set_lookup.setdefault(compact(sn), sn)
            if sc:
                self._set_vocab[sc] = sn
                self._set_lookup.setdefault(sc, sn)
                self._set_lookup.setdefault(compact(sc), sn)
                self._known_set_codes.add(sc)

        # Sellers write "Alpha"/"Beta" for Limited Edition Alpha/Beta. These are
        # only set lookups (not SET_ALIASES), so "Alpha Kavu" keeps its name.
        for short, full in (("alpha", "limited edition alpha"), ("beta", "limited edition beta")):
            if full in self._set_vocab:
                self._set_lookup.setdefault(short, full)

        for term in self.metadata_terms:
            self._metadata_lookup.setdefault(compact(term), term)

        self._compact_of = {}
        for name in self.unique_names:
            cn = compact(name)
            if not cn:
                continue
            self._compact_of[name] = cn
            self._compact_name_map.setdefault(cn, []).append(name)
            # Parenthetical Scryfall names can be matched without scanning all
            # 500k+ names on every unresolved row.
            base = norm(re.sub(r"\s*\([^()]*\)\s*$", "", name))
            if base and base != norm(name):
                bcn = compact(base)
                if bcn:
                    self._compact_base_name_map.setdefault(bcn, []).append(name)
            self._length_name_index.setdefault(len(cn), []).append(name)
            for tok in set(re.findall(r"[a-z0-9]+", norm(name))) | set(_name_words(name)):
                if len(tok) >= 3:
                    self._token_name_index.setdefault(tok, []).append(name)

    def load_search_cache(self):
        try:
            return json.loads(SEARCH_CACHE.read_text(encoding="utf-8")) if SEARCH_CACHE.exists() else {}
        except Exception:
            return {}

    def save_search_cache(self):
        try:
            SEARCH_CACHE.write_text(json.dumps(self.cache, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def ensure_bulk(self):
        self.log(f"Data folder: {DATA_DIR}")
        self.log("Magic card list (identifies Magic cards; prices come from TCGplayer): checking for updates...")
        r = requests.get(BULK_API, headers=UA, timeout=30)
        r.raise_for_status()
        data = r.json()
        meta = next((x for x in data.get("data", []) if x.get("type") == "all_cards"), None)
        if not meta:
            raise RuntimeError("Scryfall All Cards bulk-data entry was not found.")
        download_uri = meta.get("download_uri") or meta.get("jsonl_download_uri")
        if not download_uri:
            raise RuntimeError("Scryfall did not provide a bulk-data download URI.")

        old = {}
        if BULK_META.exists():
            try:
                old = json.loads(BULK_META.read_text(encoding="utf-8"))
            except Exception:
                pass
        current = {"id": meta.get("id"), "updated_at": meta.get("updated_at"), "download_uri": download_uri}

        # Fast path: the persistent cache and its metadata agree with Scryfall.
        if BULK_GZ.exists() and old.get("id") == current["id"] and old.get("updated_at") == current["updated_at"]:
            self.log("Magic card list is up to date.")
            return

        # If a user supplied an existing bulk file but no usable metadata, use it
        # rather than blindly downloading hundreds of MB. We record that the file
        # was locally adopted; the next launch will perform only the small metadata
        # request above and, if Scryfall has a newer updated_at, download once.
        if BULK_GZ.exists() and not old:
            self.log("Using the Magic card list already on this computer.")
            BULK_META.write_text(json.dumps({
                **current,
                "source": "existing-local-bulk",
                "adopted_without_download": True,
            }, indent=2), encoding="utf-8")
            if INDEX.exists():
                try:
                    INDEX.unlink()
                except OSError:
                    pass
            return

        self.log("Downloading the latest Magic card list from Scryfall (about 400 MB)...")
        tmp = DATA_DIR / "scryfall_all_cards.jsonl.download.tmp"
        try:
            with requests.get(download_uri, headers=UA, stream=True, timeout=180) as rr:
                rr.raise_for_status()
                total = int(rr.headers.get("content-length", "0") or 0)
                got = 0
                with open(tmp, "wb") as f:
                    for chunk in rr.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            if total and (got % (50 * 1024 * 1024) < 1024 * 1024):
                                self.log(f"  Downloaded {got/1024/1024:.1f} / {total/1024/1024:.1f} MB")
            tmp.replace(BULK_GZ)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        BULK_META.write_text(json.dumps(current, indent=2), encoding="utf-8")
        if INDEX.exists():
            INDEX.unlink()
        self.log("Magic card list downloaded.")

    def build(self):
        if INDEX.exists():
            try:
                d = pickle.loads(INDEX.read_bytes())
                if d.get("version") != INDEX_VERSION:
                    raise ValueError("old index version")
                self.cards = d["cards"]
                self.names = d["names"]
                self.unique_names = d["unique_names"]
                self.metadata_terms = set(d.get("metadata_terms", []))
                self.set_terms = set(d.get("set_terms", []))
                if not self.metadata_terms or not self.set_terms:
                    self._build_metadata_terms()
                self._build_runtime_indexes()
                self.log(f"Magic card list loaded: {len(self.cards):,} printings.")
                self.self_test()
                return
            except Exception as e:
                self.log(f"Cached index rejected ({e}); rebuilding from bulk data...")

        self.log("Indexing the Magic card list (after each Scryfall update, about 2 minutes)...")
        self.cards = []
        self.names = {}
        with gzip.open(BULK_GZ, "rt", encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                card = {
                    "id": c.get("id"),
                    "name": c.get("name", ""),
                    "set": c.get("set", ""),
                    "set_name": c.get("set_name", ""),
                    "set_type": c.get("set_type", ""),
                    "released_at": c.get("released_at", ""),
                    "collector_number": c.get("collector_number", ""),
                    "lang": c.get("lang", ""),
                    "oracle_id": c.get("oracle_id", ""),
                    "printed_name": c.get("printed_name", ""),
                    "finishes": c.get("finishes") or [],
                    "frame_effects": c.get("frame_effects") or [],
                    "promo_types": c.get("promo_types") or [],
                    "frame": c.get("frame", ""),
                    "security_stamp": c.get("security_stamp", ""),
                    "watermark": c.get("watermark", ""),
                    "flavor_name": c.get("flavor_name", ""),
                    "flavor_text": c.get("flavor_text", ""),
                    "artist": c.get("artist", ""),
                    "card_faces_names": [f.get("name", "") for f in (c.get("card_faces") or []) if f.get("name")],
                    "full_art": bool(c.get("full_art")),
                    "oversized": bool(c.get("oversized")),
                    "booster": c.get("booster"),
                    "story_spotlight": bool(c.get("story_spotlight")),
                    "border": c.get("border", ""),
                    "border_color": c.get("border_color", ""),
                    "promo": bool(c.get("promo")),
                    "digital": bool(c.get("digital")),
                    "variation": bool(c.get("variation")),
                    "prices": c.get("prices") or {},
                    "tcgplayer_id": c.get("tcgplayer_id"),
                    "tcgplayer_etched_id": c.get("tcgplayer_etched_id"),
                    "image": (c.get("image_uris") or {}).get("normal", ""),
                    "scryfall_uri": c.get("scryfall_uri", ""),
                }
                self.cards.append(card)
                for nm in {card["name"], card.get("printed_name", "")}:
                    if nm:
                        self.names.setdefault(norm(nm), []).append(card)
                for face in c.get("card_faces") or []:
                    fn = face.get("name", "")
                    if fn:
                        self.names.setdefault(norm(fn), []).append(card)

        self.unique_names = sorted(self.names.keys())
        self._build_metadata_terms()
        self._build_runtime_indexes()
        self.self_test()
        INDEX.write_bytes(pickle.dumps({
            "version": INDEX_VERSION,
            "cards": self.cards,
            "names": self.names,
            "unique_names": self.unique_names,
            "metadata_terms": sorted(self.metadata_terms),
            "set_terms": sorted(self.set_terms),
        }, pickle.HIGHEST_PROTOCOL))
        self.log(f"Magic card list indexed: {len(self.cards):,} printings.")
        
    def _build_metadata_terms(self):
        """Learn treatment vocabulary directly from the current Scryfall bulk data."""
        terms = set()
        set_terms = set()
        for c in self.cards:
            sn = norm(c.get("set_name", ""))
            if sn:
                set_terms.add(sn)
            for key in ("frame_effects", "promo_types"):
                for value in c.get(key) or []:
                    n = norm(value)
                    if n:
                        terms.add(n)
            for key in ("frame", "border", "security_stamp", "watermark"):
                value = norm(c.get(key, ""))
                if value:
                    terms.add(value)
        # Compound metadata labels are useful too, but keep only reasonably
        # descriptive terms so ordinary card names aren't swallowed.
        self.metadata_terms = {x for x in terms if len(_clue_tokens(x)) <= 4}
        self.set_terms = set_terms

    def enrich_parsed_with_metadata(self, parsed):
        """Discover set/treatment clues using bounded lookups, not full scans.

        IMPORTANT PERFORMANCE RULE:
        Never iterate over every Scryfall set or metadata term for every input
        row.  A 2,400-row dirty CSV would otherwise perform millions of regex
        searches before processing even begins.  Instead we generate only the
        small number of phrases that can actually occur in this row and look
        them up in O(1) dictionaries built once from Scryfall.
        """
        source = expand_card_name_shorthand(parsed.get("raw", parsed.get("name", "")))
        _condition, source = extract_title_condition(source)
        source = re.sub(r"\([^()]*\)", " ", source)
        source = GRADED_RE.sub("", source)
        source = GRADED_WORD_RE.sub("", source)
        for token in parsed.get("language_tokens") or []:
            source = re.sub(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", " ", source, flags=re.I)
        source = re.sub(r"\bserial(?:ized)?\b|\bserial\s+numbered\b", "", source, flags=re.I)
        for sp in parsed.get("set_cues") or []:
            source = re.sub(r"(?<![\w'])" + re.escape(sp) + r"(?![\w'])", " ", source, flags=re.I)
        if parsed.get("collector_number"):
            source = re.sub(r"(?:#|[-–—]\s*)" + re.escape(parsed["collector_number"]) + r"\s*$", "", source)
        source = re.sub(r"\betched(?:\s+foil)?\b|\bfoil\b", "", source, flags=re.I)
        source = re.sub(r"\s+", " ", source).strip(" -")

        # ---- Fast set lookup -------------------------------------------------
        set_found = list(parsed.get("set_cues") or [])
        set_found_norm = {norm(x) for x in set_found}

        # Generate only 1..6 word phrases from the current row.  This catches
        # ordinary set names ("Aetherdrift"), multi-word names, and set codes
        # such as "DFT" without scanning the entire Scryfall set vocabulary.
        src_words = re.findall(r"[A-Za-z0-9'’.-]+", source)
        max_set_words = 6
        # Longest phrase first, so "ice age" wins over the set code "ice".
        i = 0
        while i < len(src_words):
            step = 1
            for j in range(min(len(src_words), i + max_set_words), i, -1):
                phrase = " ".join(src_words[i:j])
                pn = norm(phrase)
                if len(pn) < 3:
                    continue
                canonical = self._set_lookup.get(pn) or self._set_lookup.get(compact(pn))
                if not canonical:
                    continue
                # Never consume the entire input when it is itself an exact
                # card name (e.g. a card named after a set).
                if norm(parsed.get("raw", "")) == pn and self.names.get(pn):
                    continue
                if canonical not in set_found_norm:
                    set_found.append(canonical)
                    set_found_norm.add(norm(canonical))
                    source = re.sub(r"(?<![\w'])" + re.escape(phrase) + r"(?![\w'])", " ", source, count=1, flags=re.I)
                step = j - i
                break
            i += step

        # Parenthetical annotations are especially useful for set names.
        alias_to_canonical = {}
        for alias, targets in SET_ALIASES.items():
            for target in targets:
                alias_to_canonical[norm(alias)] = norm(target)
        for clue in parsed.get("treatment_phrases") or []:
            cn = norm(clue)
            canonical = alias_to_canonical.get(cn)
            if not canonical:
                canonical = self._set_lookup.get(cn) or self._set_lookup.get(compact(cn))
            if canonical:
                set_found.append(canonical)
                set_found_norm.add(norm(canonical))

        parsed["set_cues"] = unique(set_found)

        # ---- Fast treatment lookup ------------------------------------------
        # Only examine suffix phrases from the actual input.  Scryfall metadata
        # terms are limited to the vocabulary learned from the current bulk
        # data, but we never loop over that vocabulary for every card.
        name = source
        found = list(parsed.get("treatment_phrases") or [])
        found_norm = {norm(x) for x in found}
        words = name.split()
        max_meta_words = 4
        consumed = 0
        # Treatments in collection exports overwhelmingly occur at the end of
        # the title ("Borderless Poster", "Galaxy Foil", etc.). Check suffixes
        # from longest to shortest so a specific treatment wins over a generic
        # shorter phrase.
        for length in range(min(max_meta_words, len(words)), 0, -1):
            tail = " ".join(words[-length:])
            key = compact(tail)
            term = self._metadata_lookup.get(key)
            if not term:
                continue
            if norm(term) in {"foil", "nonfoil", "etched", "showcase", "borderless"}:
                continue
            if norm(term) not in found_norm:
                found.append(term)
                found_norm.add(norm(term))
            words = words[:-length]
            break

        parsed["name"] = " ".join(words).strip(" -")
        parsed["name_norm"] = norm(parsed["name"])
        parsed["compact"] = compact(parsed["name"])
        parsed["name_variants"] = unique([parsed["name"]])
        parsed["treatment_phrases"] = unique(found)
        parsed["variant_terms"] = unique(found)
        return parsed

    def self_test(self):
        missing = [x for x in SELF_TEST_NAMES if not self.names.get(norm(x))]
        if missing:
            raise RuntimeError("Scryfall index self-test FAILED. Missing exact names: " + ", ".join(missing))
        self.log("Magic card list self-test passed.")
        self.log("  Exact-name checks: " + ", ".join(SELF_TEST_NAMES))

    def _name_hits(self, name):
        cache_key = norm(name)
        if cache_key in self._name_hits_cache:
            return self._name_hits_cache[cache_key]

        hits = self.names.get(cache_key, [])
        if hits:
            result = unique_cards(hits)
            self._name_hits_cache[cache_key] = result
            return result

        comp = compact(name)
        if not comp:
            self._name_hits_cache[cache_key] = []
            return []

        out = []
        for key in self._compact_name_map.get(comp, []):
            out.extend(self.names.get(key, []))

        # Parenthetical Scryfall names use a prebuilt O(1) base-name index.
        if not out:
            for key in self._compact_base_name_map.get(comp, []):
                out.extend(self.names.get(key, []))

        result = unique_cards(out)
        self._name_hits_cache[cache_key] = result
        return result

    def _explains_leftover(self, words):
        """True when every leftover word is a set, treatment, condition,
        language, grading or finish clue rather than part of a card name."""
        i = 0
        while i < len(words):
            for j in range(min(len(words), i + 6), i, -1):
                phrase = " ".join(words[i:j])
                joined = phrase.replace(" ", "")
                if (phrase in _SET_ALIAS_WORDS or phrase in self._set_lookup or joined in self._set_lookup
                        or joined in self._metadata_lookup
                        or (j - i == 1 and (phrase in LEFTOVER_NOISE_WORDS or re.fullmatch(r"\d+[a-z]?", phrase)))):
                    i = j
                    break
            else:
                return False
        return True

    def _embedded_exact_name(self, raw):
        """Find a canonical card name inside dirty text.

        The name must appear as whole words, and every other word in the text
        must be a recognizable clue (set, condition, foil, grade, ...).
        Otherwise "Mox Diamondback" would become Mox Diamond and "Lotus of
        the Abyss" would become The Abyss.
        """
        cache_key = norm(raw)
        if cache_key in self._embedded_cache:
            return self._embedded_cache[cache_key]
        raw_words = _name_words(raw)
        if not raw_words:
            self._embedded_cache[cache_key] = None
            return None

        lookup_tokens = {t for t in raw_words + re.findall(r"[a-z0-9]+", cache_key) if len(t) >= 3}
        candidate_names = set()
        pools = []
        for tok in lookup_tokens:
            hits = self._token_name_index.get(tok)
            if hits:
                pools.append((len(hits), hits))
        pools.sort(key=lambda x: x[0])
        for _, hits in pools[:4]:
            candidate_names.update(hits)

        best = None
        for name in sorted(candidate_names, key=lambda n: len(compact(n)), reverse=True):
            name_words = _name_words(name)
            n = len(name_words)
            if not n or len(compact(name)) < 3:
                continue
            for start in range(len(raw_words) - n + 1):
                if raw_words[start:start + n] == name_words:
                    if self._explains_leftover(raw_words[:start]) and self._explains_leftover(raw_words[start + n:]):
                        best = name
                    break
            if best:
                break
        self._embedded_cache[cache_key] = best
        return best

    def _strict_fuzzy_name(self, name):
        q = norm(name)
        if q in self._fuzzy_cache:
            return self._fuzzy_cache[q]
        qc = compact(q)
        if not qc:
            result = (None, 0.0, 0.0)
            self._fuzzy_cache[q] = result
            return result

        pool = set()
        qtokens = [t for t in re.findall(r"[a-z0-9]+", q) if len(t) >= 3]
        for tok in qtokens:
            pool.update(self._token_name_index.get(tok, ()))
        # Always include names of similar length: a misspelled single word
        # ("Tarmagoyf") shares no token with the real name.
        qlen = len(qc)
        radius = max(2, min(6, qlen // 5))
        for ln in range(max(1, qlen-radius), qlen+radius+1):
            pool.update(self._length_name_index.get(ln, ()))

        # Keep the names that share the most letter pairs with the query, so
        # the real name is never cut by an arbitrary pool limit.
        if len(pool) > 600:
            qgrams = _bigrams(qc)
            compact_of = getattr(self, "_compact_of", {})

            def gram_score(k):
                kg = _bigrams(compact_of.get(k) or compact(k))
                return len(qgrams & kg) / len(qgrams | kg)
            pool = heapq.nlargest(600, pool, key=gram_score)

        # Score on spelling similarity alone; a single-word typo shares no
        # whole word with the real name, so word overlap must not count.
        scored = []
        for key in pool:
            kc = compact(key)
            if kc:
                scored.append((SequenceMatcher(None, qc, kc).ratio(), key))
        if not scored:
            result = (None, 0.0, 0.0)
            self._fuzzy_cache[q] = result
            return result
        scored.sort(reverse=True)
        best_ratio, best_key = scored[0]

        # The runner-up must be a different card: a foreign printed name of
        # the same card ("Llanowarelfen") is not a competing guess.
        def card_identity(key):
            hits = self.names.get(key) or []
            return norm(hits[0].get("name", "")) if hits else key
        best_identity = card_identity(best_key)
        # On a near tie, resolve to the English name rather than a foreign
        # printed name of the same card, so English printings are priced.
        if best_key != best_identity:
            english = next((r for r, k in scored if k == best_identity), None)
            if english is not None and english >= best_ratio - 0.02:
                best_key = best_identity
        second_ratio =next((r for r, k in scored[1:] if card_identity(k) != best_identity), 0.0)
        margin = best_ratio - second_ratio
        min_ratio = 0.86 if len(qc) >= 8 else 0.9
        if best_ratio >= min_ratio and (margin >= 0.05 or best_ratio >= 0.95):
            result = (best_key, best_ratio, margin)
        else:
            result = (None, best_ratio, margin)
        self._fuzzy_cache[q] = result
        return result


    def _descriptor_hits(self, words, parsed):
        """Descriptor-prefix lookup ("Green Chaos Emerald" -> "Chaos Emerald").

        The prefix is only accepted when Scryfall metadata for the hit
        actually mentions it; otherwise "Lotus of the Abyss" would become
        The Abyss and "Blue-Eyes White Dragon" would become White Dragon.
        """
        for start in range(1, min(3, len(words) - 1) + 1):
            tail = " ".join(words[start:]).strip()
            if not tail:
                continue
            hits = self._name_hits(tail)
            if not hits:
                continue
            probe = {"descriptor_terms": [" ".join(words[:start])]}
            described = [c for c in hits
                         if descriptor_match_score(c, probe) and norm(probe["descriptor_terms"][0]) not in norm(c.get("name", ""))]
            if described:
                parsed.setdefault("descriptor_terms", []).append(probe["descriptor_terms"][0])
                return unique_cards(hits)
        return None

    def candidates(self, parsed):
        embedded = self._embedded_exact_name(expand_card_name_shorthand(parsed.get("raw", "")))
        if embedded:
            parsed["name"] = embedded
            parsed["name_norm"] = norm(embedded)
            parsed["compact"] = compact(embedded)
            parsed["name_variants"] = [embedded]
            parsed["exact_embedded_name"] = True
        else:
            parsed["exact_embedded_name"] = False
        self.enrich_parsed_with_metadata(parsed)
        # Re-assert the embedded canonical name after metadata enrichment.
        # Metadata vocabulary must never be allowed to consume part of a known
        # card title (for example the word "Tawnos" in Candelabra of Tawnos).
        if embedded:
            parsed["name"] = embedded
            parsed["name_norm"] = norm(embedded)
            parsed["compact"] = compact(embedded)
            parsed["name_variants"] = [embedded]
        # Some modern Secret Lair variants are commonly entered with a
        # descriptor before the card name (e.g. "Green Chaos Emerald") even
        # though Scryfall's canonical card name is "Chaos Emerald (Lotus Petal)".
        # Preserve the descriptor as a clue, but search the trailing phrase as
        # a possible canonical card name before falling back to fuzzy matching.
        # 1. Exact canonical name is authoritative. Never let a Scryfall
        # search alias or fuzzy result replace an exact canonical card name.
        exact_hits = self.names.get(parsed["name_norm"], [])
        if exact_hits:
            return unique_cards(exact_hits), "EXACT"
        if not embedded:
            raw_words = re.findall(r"[A-Za-z0-9'’.-]+", parsed.get("name", ""))
            if len(raw_words) >= 3:
                hits = self._descriptor_hits(raw_words, parsed)
                if hits:
                    return hits, "NORMALIZED"

        # 2. Normalized/base-name matches are allowed when Scryfall has a
        # parenthetical printing name (e.g. Chaos Emerald (Lotus Petal)).
        for name in parsed["name_variants"]:
            hits = self._name_hits(name)
            if hits:
                return unique_cards(hits), "NORMALIZED"

        # 3. Descriptor-prefix fallback. Collection lists often say things like
        # "Green Chaos Emerald" while the canonical Scryfall name is different.
        words = parsed["name"].split()
        hits = self._descriptor_hits(words, parsed) if len(words) >= 3 else None
        if hits:
            return hits, "NORMALIZED"

        # 4. CPU-heavy fuzzy matching, local only. No network request is made
        # here; unresolved names remain visible for manual review.
        fuzzy_name, fuzzy_score, fuzzy_margin = self._strict_fuzzy_name(parsed["name"])
        # A typo followed by words that aren't part of the name (a misspelled
        # set, a note): try the leading words, at a stricter 0.9 ratio.
        lead = parsed["name"].split()
        for n in range(len(lead) - 1, 1, -1):
            if fuzzy_name:
                break
            guess, score, margin = self._strict_fuzzy_name(" ".join(lead[:n]))
            if guess and score >= 0.9:
                fuzzy_name, fuzzy_score, fuzzy_margin = guess, score, margin
                parsed.setdefault("parse_warnings", []).append(
                    "IGNORED WORDS: " + " ".join(lead[n:]))
        if fuzzy_name:
            hits=self._name_hits(fuzzy_name)
            if hits:
                parsed["resolved_name"]=fuzzy_name
                parsed["fuzzy_name_score"]=fuzzy_score
                parsed["fuzzy_name_margin"]=fuzzy_margin
                return unique_cards(hits), "FUZZY"
        return [], "NO MATCH"

_SET_ALIAS_WORDS = {" ".join(_name_words(k)) for k in SET_ALIASES}

# Words that can sit next to a card name in a dirty title without being part
# of it: finish, grading, language, condition, treatment and filler words.
LEFTOVER_NOISE_WORDS = (
    {"foil", "foils", "etched", "nonfoil", "non", "normal", "signed", "autographed", "graded", "slab", "slabbed",
     "holo", "x", "edition", "ed", "mtg", "magic", "condition", "psa", "bgs", "cgc", "sgc", "tag", "beckett",
     "gem", "pristine", "showcase", "borderless", "extended", "art", "alternate", "alt", "retro", "frame",
     "full", "promo", "prerelease", "stamped", "textless", "misprint", "serialized", "serial", "numbered",
     "alpha", "beta", "unlimited", "revised", "copy", "copies", "card"}
    | {w for k in CONDITION_ALIASES for w in _name_words(k)}
    | {w for k in LANGUAGE_ALIASES for w in _name_words(k)}
)

def unique_cards(cards):
    out = []
    seen = set()
    for c in cards:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            out.append(c)
    return out

def set_matches(card, cue):
    sn = norm(card.get("set_name", ""))
    aliases = SET_ALIASES.get(norm(cue), [cue])
    if norm(cue) == "promo":
        return bool(card.get("promo")) or "promo" in sn
    return any(a in sn or sn == a for a in map(norm, aliases))

def finish_matches(card, finish):
    finishes = set(card.get("finishes") or [])
    if finish == "foil":
        return "foil" in finishes
    if finish == "etched":
        return "etched" in finishes
    return "nonfoil" in finishes

def _metadata_values(card):
    """Return normalized Scryfall metadata values usable as treatment evidence."""
    vals = []
    for key in ("frame_effects", "promo_types"):
        vals.extend(card.get(key) or [])
    for key in ("frame", "border", "security_stamp", "watermark", "flavor_name", "artist"):
        if card.get(key):
            vals.append(card.get(key))
    if card.get("full_art"):
        vals.append("full art")
    if card.get("oversized"):
        vals.append("oversized")
    if card.get("story_spotlight"):
        vals.append("story spotlight")
    if card.get("booster") is False:
        vals.append("not booster")
    return [norm(v) for v in vals if v]

def _clue_tokens(text):
    # Treat spaces, hyphens and punctuation as equivalent for metadata matching.
    return set(re.findall(r"[a-z0-9]+", norm(text)))

def _metadata_match_score(clue, metadata):
    """Score a free-form input clue against Scryfall metadata without a fixed list."""
    clue_n = norm(clue)
    clue_tokens = _clue_tokens(clue_n)
    if not clue_tokens:
        return 0
    best = 0
    for value in metadata:
        vt = _clue_tokens(value)
        if not vt:
            continue
        if clue_n == value or compact(clue_n) == compact(value):
            best = max(best, 3)
            continue
        if compact(value) and compact(value) in compact(clue_n):
            best = max(best, 2)
            continue
        if clue_tokens <= vt or vt <= clue_tokens:
            best = max(best, 2)
            continue
        overlap = len(clue_tokens & vt)
        if overlap and overlap / max(len(clue_tokens), len(vt)) >= 0.5:
            best = max(best, 1)

    # A user phrase can combine multiple Scryfall metadata fields. For example,
    # "Borderless Poster Foil" is finish=foil plus border=borderless plus
    # promo_type=poster. Treat the phrase as confirmed when each meaningful
    # token is represented somewhere in the metadata, even if Scryfall stores
    # those tokens in separate fields.
    metadata_tokens = set()
    for value in metadata:
        metadata_tokens.update(_clue_tokens(value))
    if clue_tokens and clue_tokens <= metadata_tokens:
        best = max(best, 3)
    return best

def variant_matches(card, parsed):
    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    if not clues:
        return 0
    metadata = _metadata_values(card)
    if not metadata:
        return 0
    return sum(1 for clue in clues if _metadata_match_score(clue, metadata) >= 2)

def variant_evidence(card, parsed):
    """Return (matched_clues, requested_clues) for precise review decisions."""
    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    metadata = _metadata_values(card)
    matched = [clue for clue in clues if _metadata_match_score(clue, metadata) >= 2]
    return matched, clues

def descriptor_values(card):
    """Human-facing descriptors that may distinguish otherwise identical cards."""
    vals = []
    for key in ("flavor_name", "printed_name", "name", "set_name", "collector_number", "artist"):
        value = card.get(key)
        if value:
            vals.append(norm(value))
    vals.extend(norm(x) for x in (card.get("card_faces_names") or []) if x)
    return vals

def descriptor_match_score(card, parsed):
    clues = parsed.get("descriptor_terms") or []
    if not clues:
        return 0
    values = descriptor_values(card)
    score = 0
    for clue in clues:
        cn = norm(clue)
        if any(cn == v or cn in v for v in values):
            score += 1
    return score

def score_candidate(c, parsed):
    q = parsed["name_norm"]
    cname = norm(c.get("name", ""))
    score = 0.0

    if cname == q:
        score += 1000
    elif compact(cname) == parsed["compact"]:
        score += 950
    else:
        score += 500 * SequenceMatcher(None, cname, q).ratio()

    # Strong explicit constraints.
    if parsed["set_cues"]:
        matched_sets = sum(1 for cue in parsed["set_cues"] if set_matches(c, cue))
        if matched_sets:
            score += 450 * matched_sets
        else:
            score -= 800

    if parsed["collector_number"]:
        if collector_number_equal(c.get("collector_number"), parsed["collector_number"]):
            score += 700
        else:
            score -= 900

    if parsed["finish"] in {"foil", "etched"}:
        if finish_matches(c, parsed["finish"]):
            score += 500
        else:
            score -= 900
    elif not parsed.get("finish_explicit") and finish_matches(c, "nonfoil"):
        score += 40

    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    dm = descriptor_match_score(c, parsed)
    if parsed.get("descriptor_terms"):
        score += 350 * dm
        if dm == 0:
            score -= 350
    vm = variant_matches(c, parsed)
    if clues:
        score += 220 * vm
        if vm == 0:
            # Metadata-driven clues are meaningful, but not every marketplace
            # phrase has a one-to-one Scryfall field. Penalize rather than reject.
            score -= 250

    if c.get("lang") == "en":
        score += 25
    if c.get("digital"):
        score -= 200
    if is_unlikely_unspecified_printing(c) and not explicitly_requests_special_printing(parsed):
        score -= 700
    # A serialized printing is a materially different product. Do not select
    # one merely because the input says "poster foil"; require an explicit
    # serialized clue. Scryfall exposes this in promo_types.
    if "serialized" in {norm(x) for x in (c.get("promo_types") or [])}:
        if parsed.get("serialized"):
            score += 250
        else:
            score -= 900

    if c.get("promo") and "promo" not in {norm(x) for x in parsed["variant_terms"]} and not parsed["set_cues"]:
        score -= 80

    return score

def filter_candidates(cands, parsed):
    """Apply hard constraints when doing so leaves a viable candidate set."""
    out = unique_cards(cands)

    if parsed["set_cues"]:
        for cue in parsed["set_cues"]:
            filtered = [c for c in out if set_matches(c, cue)]
            if filtered:
                out = filtered

    if parsed["collector_number"]:
        filtered = [c for c in out if collector_number_equal(c.get("collector_number"), parsed["collector_number"])]
        if filtered:
            out = filtered

    if parsed["finish"] in {"foil", "etched"}:
        filtered = [c for c in out if finish_matches(c, parsed["finish"])]
        if filtered:
            out = filtered

    # Never silently turn an ordinary card request into a serialized printing.
    # If the user explicitly asks for serialized, keep only serialized records.
    serialized_cards = [c for c in out if "serialized" in {norm(x) for x in (c.get("promo_types") or [])}]
    if parsed.get("serialized") and serialized_cards:
        out = serialized_cards
    elif not parsed.get("serialized") and serialized_cards:
        ordinary_cards = [c for c in out if "serialized" not in {norm(x) for x in (c.get("promo_types") or [])}]
        if ordinary_cards:
            out = ordinary_cards

    # Human-facing descriptors (e.g. Green/Blue/Purple) are treated as strong
    # clues when Scryfall exposes them in flavor/printed metadata. Do not guess
    # when Scryfall has no evidence.
    descriptor_clues = parsed.get("descriptor_terms") or []
    if descriptor_clues:
        described = [c for c in out if descriptor_match_score(c, parsed) == len(descriptor_clues)]
        if described:
            out = described

    # Explicit treatment cues are a filter only when Scryfall metadata confirms
    # at least one candidate. A fully matched clue is preferred over generic foil.
    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    if clues:
        treated = [c for c in out if all(_metadata_match_score(clue, _metadata_values(c)) >= 2 for clue in clues)]
        if treated:
            out = treated
        else:
            partial = [c for c in out if variant_matches(c, parsed) > 0]
            if partial:
                out = partial

    return out

def is_unlikely_unspecified_printing(card):
    """Printings we should not select by default unless the input asks for them."""
    if card.get("oversized"):
        return True
    sn = norm(card.get("set_name", ""))
    # World Championship Deck products are legitimate Scryfall records, but
    # are unusual collection-trade inputs unless explicitly identified.
    if "world championship" in sn:
        return True
    if "championship deck" in sn:
        return True
    # Collector's Edition products are legitimate Scryfall printings, but
    # should not be selected for an ordinary card-list entry unless explicitly
    # identified. This covers both CE and International Collector's Edition.
    # 30th Anniversary Edition is a non-tournament-legal reprint product.
    if "30th anniversary edition" in sn:
        return True
    sn = sn.replace("'", "")  # Scryfall spells it "Collectors' Edition"
    if "collectors edition" in sn:
        return True
    if "international collector" in sn or "intl. collectors" in sn or "intl collectors" in sn:
        return True
    return False

def explicitly_requests_special_printing(parsed):
    text = norm(parsed.get("raw", "")).replace("collectors'", "collectors")
    return (
        "oversized" in text
        or "world championship" in text
        or "championship deck" in text
        or "collector's edition" in text
        or "collectors edition" in text
        or "international collector" in text
        or "intl. collectors" in text
        or "intl collectors" in text
        or bool(re.search(r"\bcei\b", text))
        or bool(re.search(r"\bced\b", text))
        or "serialized" in text
        or "30th anniversary" in text
        or bool(re.search(r"\b30a\b", text))
    )

def default_rank(c, parsed):
    """Deterministic default printing: oldest real-world paper printing first."""
    release = c.get("released_at") or "9999-99-99"
    promo_penalty = 1 if c.get("promo") else 0
    digital_penalty = 1 if c.get("digital") else 0
    variation_penalty = 1 if c.get("variation") else 0
    # Lower tuple is better.
    return (digital_penalty, promo_penalty, variation_penalty, release, norm(c.get("set_name", "")), norm(c.get("collector_number", "")))

def _card_has_requested_finish(card, parsed):
    finish = parsed.get("finish", "nonfoil")
    return finish_matches(card, finish)

def _has_scryfall_price(card, parsed):
    return price_card(card, parsed)[0] is not None

def _identity_is_specific(filtered, parsed, ranked):
    """Return True only when the available evidence identifies one printing."""
    if len(filtered) == 1:
        return True

    # A set + collector number is a printing-level identity.
    if parsed.get("set_cues") and parsed.get("collector_number"):
        matches = [c for c in filtered if any(set_matches(c, cue) for cue in parsed["set_cues"]) and collector_number_equal(c.get("collector_number"), parsed["collector_number"]) ]
        if len(matches) == 1:
            return True

    # Collector number plus an explicit finish/treatment can identify a printing
    # even when the set was not written by the collector.
    if parsed.get("collector_number"):
        matches = [c for c in filtered if collector_number_equal(c.get("collector_number"), parsed["collector_number"]) ]
        if parsed.get("finish") in {"foil", "etched"}:
            matches = [c for c in matches if finish_matches(c, parsed["finish"])]
        clues = parsed.get("treatment_phrases") or []
        if clues:
            matches = [c for c in matches if all(_metadata_match_score(x, _metadata_values(c)) >= 2 for x in clues)]
        if len(matches) == 1:
            return True

    # An explicit treatment that uniquely identifies one surviving printing is
    # enough even when the card has many historical printings.
    clues = parsed.get("treatment_phrases") or []
    if clues:
        matches = [c for c in filtered if all(_metadata_match_score(x, _metadata_values(c)) >= 2 for x in clues)]
        if len(matches) == 1:
            return True

    return False

def _reorder_underdetermined_candidates(filtered, parsed):
    """Put priced applicable candidates ahead when identity remains underdetermined."""
    priced = [c for c in filtered if _has_scryfall_price(c, parsed)]
    if priced:
        return sorted(priced, key=lambda c: (
            price_card(c, parsed)[0],
            score_candidate(c, parsed) * -1,
            default_rank(c, parsed),
        )) + [c for c in filtered if c not in priced]
    return sorted(filtered, key=lambda c: (-score_candidate(c, parsed), default_rank(c, parsed)))

def choose_candidate(cands, parsed, match_type):
    if not cands:
        return None, 0.0, "NO MATCH"

    # If the collector explicitly wrote "foil" but this card has literally
    # no foil printing anywhere in the available Scryfall records, treat the
    # foil word as an erroneous finish annotation. In that one situation only,
    # fall back to the ordinary nonfoil card. We intentionally check the full
    # candidate pool here rather than only the currently filtered set, because
    # a card may have a foil printing in another set.
    if parsed.get("finish_explicit") and parsed.get("finish") == "foil":
        has_any_foil_printing = any(finish_matches(c, "foil") for c in unique_cards(cands))
        if not has_any_foil_printing:
            parsed["finish"] = "nonfoil"
            parsed["finish_explicit"] = False

    filtered = filter_candidates(cands, parsed)
    if not explicitly_requests_special_printing(parsed):
        ordinary = [c for c in filtered if not is_unlikely_unspecified_printing(c)]
        if ordinary:
            filtered = ordinary
    if not filtered:
        return None, 0.0, "NO MATCH"

    ranked = sorted(((score_candidate(c, parsed), c) for c in filtered), key=lambda x: x[0], reverse=True)
    best_score, best = ranked[0]
    second_score, second = ranked[1] if len(ranked) > 1 else (None, None)
    specific = _identity_is_specific(filtered, parsed, ranked)
    review = ""

    # When the input does not uniquely identify a printing, choose among the
    # applicable priced candidates by price. Strongly identified printings are
    # never replaced just because another printing is cheaper.
    if not specific and len(filtered) > 1:
        ordered = _reorder_underdetermined_candidates(filtered, parsed)
        if ordered:
            best = ordered[0]
            best_score = score_candidate(best, parsed)
            if not _has_scryfall_price(best, parsed):
                review = "NO PRICE"
            else:
                review = "ASSUMED PRINTING"

    # If a specifically identified printing has no applicable Scryfall price,
    # preserve that exact printing. Do not silently substitute another set.
    if specific and not _has_scryfall_price(best, parsed):
        review = "NO PRICE FOR SPECIFIC PRINTING"

    if match_type == "EXACT":
        confidence = 1.0
    elif match_type == "NORMALIZED":
        confidence = 0.99
    elif match_type == "SCRYFALL SEARCH":
        confidence = 0.97
    else:
        confidence = max(0.0, min(0.99, best_score / 1200.0))

    if match_type == "FUZZY" and review == "":
        review = "FUZZY MATCH"

    # Treatment clues are decisive when Scryfall metadata confirms them.
    clues = parsed.get("treatment_phrases") or []
    if clues:
        matching_ids = []
        for _score, c in ranked:
            matched, _ = variant_evidence(c, parsed)
            if all(norm(x) in {norm(y) for y in matched} for x in clues):
                matching_ids.append(c.get("id"))
        if len(set(matching_ids)) == 1 and matching_ids[0] == best.get("id") and review == "AMBIGUOUS PRINTING":
            review = ""

    if parsed.get("descriptor_terms") and len(filtered) > 1 and descriptor_match_score(best, parsed) == 0:
        if review == "":
            review = "AMBIGUOUS PRINTING"

    if parsed.get("finish_explicit") and parsed["finish"] in {"foil", "etched"} and not finish_matches(best, parsed["finish"]):
        review = "REQUESTED FINISH NOT CONFIRMED"

    return best, confidence, review

def effective_finish(card, parsed):
    """Return the finish actually represented by the selected printing."""
    if parsed.get("finish_explicit"):
        return parsed.get("finish", "nonfoil")
    finishes = card.get("finishes") or []
    if "nonfoil" in finishes:
        return "nonfoil"
    if "foil" in finishes:
        return "foil"
    if "etched" in finishes:
        return "etched"
    return parsed.get("finish", "nonfoil")

# TCGplayer prices from TCGCSV, set by the engine when the Magic catalog has
# been synced. Scryfall's own price fields are the fallback.
_PRICE_CATALOG = None


def set_price_catalog(catalog):
    global _PRICE_CATALOG
    _PRICE_CATALOG = catalog


def tcgplayer_product(card, parsed):
    """(product, price row) for this printing and finish in the TCGCSV catalog."""
    if _PRICE_CATALOG is None:
        return None, None
    finish = effective_finish(card, parsed)
    product = None
    if finish == "etched" and card.get("tcgplayer_etched_id"):
        product = _PRICE_CATALOG.get(card["tcgplayer_etched_id"])
    if product is None:
        product = _PRICE_CATALOG.get(card.get("tcgplayer_id"))
    if product is None:
        return None, None
    prices = product.get("prices") or {}
    row = prices.get("Normal") if finish == "nonfoil" else prices.get("Foil")
    return product, row


def price_card(card, parsed):
    product, row = tcgplayer_product(card, parsed)
    if row:
        val, basis = choose_price(row)
        if val is not None:
            return val, basis, "Price from TCGplayer (TCGCSV)"
    prices = card.get("prices") or {}
    finish = effective_finish(card, parsed)
    if finish == "foil":
        val = money(prices.get("usd_foil"))
        if val is not None:
            return val, "Scryfall USD Foil", "Price supplied by Scryfall"
        return None, "", "No Scryfall foil price"
    if finish == "etched":
        val = money(prices.get("usd_etched"))
        if val is not None:
            return val, "Scryfall USD Etched", "Price supplied by Scryfall"
        return None, "", "No Scryfall etched price"
    val = money(prices.get("usd"))
    if val is not None:
        return val, "Scryfall USD", "Price supplied by Scryfall"
    return None, "", "No Scryfall price"

def image_url(card):
    return card.get("image", "")

def matched_display_name(card, parsed):
    """Return the face name the user actually matched, not the front-face
    composite name of a double-faced card.

    Scryfall stores a transforming/double-faced card as one printing whose
    top-level ``name`` can be something like ``Eiganjo Dynastorian //
    Replenish``.  The index also maps each face name to that printing.  When
    the input is exactly a face name (for example ``Replenish``), the output
    should report that face name rather than the composite card name.
    """
    wanted = norm(parsed.get("name", ""))
    if not wanted:
        return card.get("name", "")

    if wanted == norm(card.get("name", "")):
        return card.get("name", "")

    for face_name in card.get("card_faces_names") or []:
        if wanted == norm(face_name):
            return face_name

    # ``printed_name`` can also be the name the user matched on some
    # translated/special printings.
    printed = card.get("printed_name", "")
    if printed and wanted == norm(printed):
        return printed

    return card.get("name", "")

def prewarm_fuzzy_multiprocess(db, parsed_items, log):
    """Pre-resolve only genuinely fuzzy names using up to 8 local workers.

    IMPORTANT:
      The old macOS implementation spawned processes and built/serialized large
      fuzzy indexes for each worker. On a 542k-card Scryfall database that can
      take longer than the actual pricing job and can make the GUI appear frozen.

      We keep the user-visible "8 workers" behavior, but use threads against the
      already-built in-memory indexes. Exact/normalized matches never enter this
      pool. This avoids process spawning, giant pickles, duplicated indexes, and
      macOS AppTranslocation/process crashes.
    """
    queries = []
    seen = set()

    for parsed in parsed_items:
        q = norm(parsed.get("name", ""))
        if not q or q in seen or q in db._fuzzy_cache:
            continue
        # O(1) exact/compact lookup. Only names that truly need fuzzy matching
        # are sent to the worker pool.
        if db._name_hits(q):
            continue
        seen.add(q)
        queries.append(q)

    if not queries:
        log("Turbo pre-pass: no fuzzy names needed; using indexed matching.")
        return

    workers = min(8, max(1, (mp.cpu_count() or 2) - 1))
    log(f"Turbo pre-pass: {len(queries)} unique fuzzy names on {workers} workers...")

    def resolve(q):
        return q, db._strict_fuzzy_name(q)

    try:
        # Threads share the already-built Scryfall indexes. There is no database
        # copy and no spawn/import cost. SequenceMatcher releases enough time
        # between Python operations for this to provide useful parallelism while
        # preserving the same matching algorithm.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="MTG-Fuzzy") as ex:
            completed = 0
            futures = [ex.submit(resolve, q) for q in queries]
            for fut in as_completed(futures):
                q, result = fut.result()
                db._fuzzy_cache[q] = result
                completed += 1
                if completed == len(futures) or completed % 50 == 0:
                    log(f"Turbo pre-pass: {completed}/{len(futures)} fuzzy names ready")
    except Exception as e:
        # Fuzzy prewarming is an optimization only. If a worker fails, clear
        # only the affected cache entries and let the normal local resolver run.
        log(f"Turbo worker pre-pass failed safely ({type(e).__name__}: {e}); continuing normally.")
        for q in queries:
            db._fuzzy_cache.pop(q, None)


# ======================================================================
# cardpricer/games/sealed.py
# ======================================================================

import re
from difflib import SequenceMatcher


# Words that change what the product is. A candidate that has one of these
# and the title doesn't (or the reverse) is a different product.
PRODUCT_WORDS = {"case", "half", "display", "box", "pack", "packs", "bundle", "booster", "collector", "set",
                 "draft", "play", "jumpstart", "elite", "trainer", "etb", "tin", "mini", "blister", "deck",
                 "commander", "starter", "theme", "prerelease", "kit", "premium", "collection", "sleeved",
                 "center", "exclusive", "build", "battle", "ultra", "art", "structure", "tuck", "double",
                 "master", "multipack", "retail", "hobby", "japanese", "korean", "chinese"}
# A case / half box / master case is a different product at a very
# different price; mismatching one of these weighs heavily.
MAJOR_WORDS = {"case", "half", "master", "multipack"}
FILLER_WORDS = {"sealed", "factory", "new", "unopened", "english", "the", "of", "a", "and", "x", "mtg", "magic",
                "pokemon", "yugioh", "ygo", "optcg", "riftbound", "tcg", "card", "game", "cards", "with", "in",
                "brand", "nib", "nisb", "shrink", "shrinkwrap", "shrinkwrapped", "wrapped", "sealed:",
                "1st", "edition", "unlimited"}
SYNONYMS = {"etb": ["elite", "trainer", "box"], "bb": ["booster", "box"], "upc": ["ultra", "premium", "collection"],
            "boosterbox": ["booster", "box"], "packs": ["pack"], "decks": ["deck"], "boxes": ["box"],
            "displays": ["display"], "pokémon": ["pokemon"]}


# Different names for the same product shape ("Booster Display" is what
# TCGplayer calls a Magic / One Piece booster box).
KIND_EQUIVALENTS = {"display": "box"}


def _words(text):
    # "[Set of 2]", "(Set of 4)": several units, a different product.
    text = re.sub(r"\bset\s+of\s+\d+\b", " multipack ", text or "", flags=re.I)
    out = []
    for w in _name_words(text):
        out.extend(SYNONYMS.get(w, [w]))
    return out


def _kinds(words):
    return {KIND_EQUIVALENTS.get(w, w) for w in words if w in PRODUCT_WORDS}


class SealedMatcher:
    def __init__(self, catalogs):
        """catalogs: {game: Catalog}"""
        self.products = []
        self.by_word = {}
        for game, cat in catalogs.items():
            if not cat:
                continue
            for p in cat.products.values():
                if not p["sealed"]:
                    continue
                group_words = set(_words(p["group_name"])) | {p["group_abbr"].lower()} - {""}
                words = set(_words(p["name"])) | group_words
                entry = (p, words, group_words)
                self.products.append(entry)
                for w in words - PRODUCT_WORDS - FILLER_WORDS:
                    self.by_word.setdefault(w, []).append(entry)

    def match(self, raw, games=None):
        """Return (product or None, score, review, top candidate names)."""
        _cond, text = extract_title_condition(raw or "")
        words = [w for w in _words(text) if w not in FILLER_WORDS]
        if not words:
            return None, 0.0, "SEALED - NO NAME", []
        title_kind = _kinds(words)
        title_rest = set(words) - PRODUCT_WORDS
        pool = {}
        for w in title_rest:
            for entry in self.by_word.get(w, ()):
                pool[entry[0]["id"]] = entry
        scored = []
        for p, pwords, group_words in pool.values():
            if games and p["game"] not in games:
                continue
            p_kind = _kinds(pwords)
            p_rest = pwords - PRODUCT_WORDS - FILLER_WORDS
            rest_hit = len(title_rest & p_rest) / max(1, len(title_rest))
            kind_extra = len(p_kind - title_kind)       # product words the title didn't say
            kind_missing = len(title_kind - p_kind)     # title words this product lacks
            # Name words beyond the set name that the title never mentioned
            # ("Nightmare" Bundle when the title says just "Bundle").
            name_extra = len(p_rest - group_words - title_rest)
            seq = SequenceMatcher(None, " ".join(words), " ".join(_words(p["name"]))).ratio()
            major = len((p_kind ^ title_kind) & MAJOR_WORDS)
            score = (rest_hit * 0.6 + seq * 0.4 - 0.15 * kind_extra - 0.2 * kind_missing - 0.1 * name_extra
                     - 0.3 * major)
            scored.append((score, p))
        if not scored:
            return None, 0.0, "SEALED - NO MATCH", []
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        top = [f"{p['name']} ({p['group_name']})" for _s, p in scored[:3]]
        if best_score >= 0.6 and best_score - second >= 0.05:
            return best, best_score, "", top
        if best_score >= 0.6:
            return None, best_score, "SEALED - SEVERAL PRODUCTS MATCH", top
        return None, best_score, "SEALED - NO CONFIDENT MATCH", top


# ======================================================================
# cardpricer/games/tcg.py
# ======================================================================

import heapq
import re
from difflib import SequenceMatcher


# Words in a title that name the game itself.
GAME_TITLE_WORDS = {
    "magic": ("mtg", "magic the gathering", "magic: the gathering"),
    "pokemon": ("pokemon", "pokémon", "ptcg", "pkmn"),
    "yugioh": ("yugioh", "yu-gi-oh!", "yu-gi-oh", "ygo"),
    "onepiece": ("one piece tcg", "one piece card game", "optcg"),
    "riftbound": ("riftbound",),
}

# Card-number shapes, most specific first.
NUMBER_PATTERNS = [
    re.compile(r"(?<![\w/])([A-Za-z]{0,4}\d{1,4}[a-zA-Z*]?\s?/\s?[A-Za-z]{0,4}\d{1,4})(?![\w/])"),  # 025/165, TG03/TG30
    re.compile(r"(?<![\w-])([A-Za-z0-9]{2,5}-[A-Za-z]{0,3}\d{1,4}[a-zA-Z]?)(?![\w-])"),             # LOB-EN001, OP01-120
    re.compile(r"(?<![\w-])((?:SWSH|SM|XY|BW|SVP|SV|HGSS|DP|NP|MEP|TG|GG|RC|SVE)\s?\d{1,3})(?![\w-])", re.I),
    re.compile(r"#\s?(\d{1,4}[a-zA-Z]?)\b"),
]

# Finish words -> words the TCGplayer subtype must contain (Pokémon:
# Normal / Holofoil / Reverse Holofoil / 1st Edition (Holofoil) / Unlimited
# (Holofoil); Yu-Gi-Oh: 1st Edition / Unlimited / Limited; One Piece and
# Riftbound: Normal / Foil).
FINISH_PHRASES = [
    (r"reverse\s+holo(?:foil)?|rev\s+holo|reverse|\brh\b", {"reverse"}),
    (r"1st\s+ed(?:ition|\.)?\s+holo(?:foil)?|first\s+edition\s+holo(?:foil)?", {"1st", "holofoil"}),
    (r"unlimited\s+holo(?:foil)?", {"unlimited", "holofoil"}),
    (r"1st\s+ed(?:ition|\.)?|first\s+edition|\b1st\b", {"1st"}),
    (r"\bunlimited\b|\bunl\b", {"unlimited"}),
    (r"\blimited\s+edition\b", {"limited"}),
    (r"non[\s-]?holo|non[\s-]?foil|nonfoil", {"normal"}),
    (r"\bholo(?:foil|graphic)?\b", {"holofoil"}),
    (r"\bfoil\b", {"foil"}),
]
# Variant / rarity words, kept as clues and checked against the product's
# name tags and rarity. Short forms map to TCGplayer's wording.
VARIANT_SYNONYMS = {
    "alt art": "alternate art", "aa": "alternate art", "sir": "special illustration rare",
    "ir": "illustration rare", "fa": "full art", "qcsr": "quarter century secret rare",
    "ex art": "extended art", "sar": "special art rare",
}
VARIANT_PHRASES = sorted({
    "special illustration rare", "illustration rare", "hyper rare", "secret rare", "ultra rare", "super rare",
    "ultimate rare", "starlight rare", "ghost rare", "quarter century secret rare", "platinum secret rare",
    "prismatic secret rare", "collector's rare", "gold rare", "premium gold rare", "rainbow rare", "shiny rare",
    "alternate art", "alt art", "full art", "extended art", "manga", "parallel", "overnumbered", "showcase",
    "special art", "sp", "sir", "ir", "aa", "fa", "qcsr", "sar", "shadowless", "prerelease", "staff", "stamped",
    "promo", "jumbo", "oversized", "signature", "textured", "gold", "shiny", "radiant", "error", "misprint",
}, key=len, reverse=True)

# Names sellers use for sets that differ from TCGplayer's set name.
SET_NICKNAMES = {
    "pokemon": {"151": "SV: Scarlet & Violet 151", "base": "Base Set", "base set unlimited": "Base Set",
                "shadowless": "Base Set (Shadowless)", "1st edition base set": "Base Set (Shadowless)"},
}

# Per game: words used in card names that must not be read as conditions.
NAME_WORDS = {"pokemon": ("ex",), "onepiece": ("sp",), "yugioh": (), "riftbound": ()}

# Sealed words beyond the shared SEALED_RE. These only count when the rest of
# the title is not a card name ("Structure Deck" is also a set name).
TCG_SEALED_RE = re.compile(
    r"\b(?:elite\s+trainer\s+box|etb|blister|booster\s+bundle|build\s*(?:&|and)\s*battle|premium\s+collection"
    r"|ultra[\s-]premium\s+collection|upc|collection\s+box|mini\s+tin|tin|booster\s+display|display\s+box"
    r"|display|sleeved\s+booster|structure\s+deck|starter\s+deck|tuck\s+box|double\s+pack|deck\s+set"
    r"|booster\s+pack|booster\s+box|booster|case|half\s+booster\s+box)\b", re.I)


def number_key(num):
    """Comparable card number: "025/165" -> "25/165", "TG03" -> "tg3"."""
    s = re.sub(r"\s+", "", norm(num)).replace("*", "")
    return re.sub(r"\d+", lambda m: str(int(m.group())), s)


def core_name(name):
    """Card identity name: tags and trailing numbers removed.
    "Nami (OP01-016) (SP)" -> "Nami", "Pikachu - 173/165" -> "Pikachu"."""
    s = re.sub(r"\s*\([^()]*\)", "", name or "")
    s = re.sub(r"\s*\[[^\[\]]*\]", "", s)
    s = re.sub(r"\s+-\s+[A-Za-z0-9]*\d[A-Za-z0-9/\-]*\s*$", "", s)
    return s.strip()


def name_key(name):
    return " ".join(_name_words(name))


def product_tags(product):
    """Variant tags TCGplayer puts in brackets, excluding pure numbers/codes."""
    tags = re.findall(r"\(([^()]*)\)", product["name"]) + re.findall(r"\[([^\[\]]*)\]", product["name"])
    return [t for t in tags if not re.fullmatch(r"[A-Za-z]{0,4}\d{1,4}[a-z]?|[A-Za-z0-9]{2,5}-[A-Za-z]{0,3}\d{1,4}", t.strip())]


def is_promo(product):
    return (norm(product.get("rarity", "")) in {"promo", "pr"}
            or "promo" in norm(product.get("group_name", "")))


def variant_text(product):
    return norm(" ".join(product_tags(product) + [product.get("rarity", "")]))


class NameIndex:
    """Exact and strict typo-tolerant lookup over one game's card names."""

    def __init__(self, keys):
        self.keys = set(keys)
        self.by_length = {}
        self.by_token = {}
        for k in self.keys:
            c = k.replace(" ", "")
            self.by_length.setdefault(len(c), []).append(k)
            for tok in k.split():
                if len(tok) >= 3:
                    self.by_token.setdefault(tok, []).append(k)
        self.cache = {}

    def fuzzy(self, query):
        """(key, ratio) for a confident single best match, else (None, ratio)."""
        q = name_key(query)
        if q in self.cache:
            return self.cache[q]
        qc = q.replace(" ", "")
        if len(qc) < 4:
            return None, 0.0
        pool = set()
        for tok in q.split():
            pool.update(self.by_token.get(tok, ()))
        radius = max(2, min(6, len(qc) // 5))
        for ln in range(max(1, len(qc) - radius), len(qc) + radius + 1):
            pool.update(self.by_length.get(ln, ()))
        if len(pool) > 600:
            qg = _bigrams(qc)
            pool = heapq.nlargest(600, pool, key=lambda k: len(qg & _bigrams(k.replace(" ", ""))) / len(qg | _bigrams(k.replace(" ", ""))))
        scored = sorted(((SequenceMatcher(None, qc, k.replace(" ", "")).ratio(), k) for k in pool), reverse=True)
        if not scored:
            return None, 0.0
        best_ratio, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        ok = best_ratio >= (0.86 if len(qc) >= 8 else 0.9) and (best_ratio - second >= 0.05 or best_ratio >= 0.95)
        result = (best if ok else None, best_ratio)
        self.cache[q] = result
        return result


class TCGMatcher:
    """Identify cards of one TCGCSV game."""

    def __init__(self, game, catalog):
        self.game = game
        self.catalog = catalog
        self.by_core = {}
        self.by_number = {}
        for p in catalog.products.values():
            if p["sealed"]:
                continue
            self.by_core.setdefault(name_key(core_name(p["name"])), []).append(p)
            if p["number"]:
                for part in re.split(r"\s*//\s*", p["number"]):
                    key = number_key(part)
                    self.by_number.setdefault(key, []).append(p)
                    if "/" in key:
                        self.by_number.setdefault(key.split("/")[0], []).append(p)
        self.names = NameIndex(self.by_core)
        self.set_lookup = {}       # phrase -> {groupId}
        self.set_abbrs = set()     # upper-case abbreviations, matched case-sensitively
        # Full set names first; shortened forms ("Evolving Skies" for
        # "SWSH07: Evolving Skies", "Base Set" for "Base Set (Shadowless)")
        # only where they don't name another set exactly.
        short_keys = []
        for gid, g in catalog.groups.items():
            name = g.get("name", "")
            self.set_lookup.setdefault(name_key(name), set()).add(gid)
            short = {norm(re.sub(r"\s*\([^()]*\)", "", name))}
            m = re.match(r"^([A-Za-z0-9&\- ]{1,12}):\s*(.+)$", name)
            if m:
                short.update({norm(m.group(2)), norm(re.sub(r"\s*\([^()]*\)", "", m.group(2)))})
                if re.search(r"\d", m.group(1)):
                    short.add(norm(m.group(1)))
            short_keys += [(name_key(k), gid) for k in short if k]
            abbr = (g.get("abbreviation") or "").strip()
            if len(abbr) >= 2:
                self.set_abbrs.add(abbr.upper())
                self.set_lookup.setdefault("abbr:" + abbr.upper(), set()).add(gid)
                # "ST01" and "ST-01" are the same code.
                self.set_lookup.setdefault("abbr:" + re.sub(r"[^A-Z0-9]", "", abbr.upper()), set()).add(gid)
        full = set(self.set_lookup)
        for key, gid in short_keys:
            if key and key not in full:
                self.set_lookup.setdefault(key, set()).add(gid)
        for alias, target in SET_NICKNAMES.get(game, {}).items():
            gids = self.set_lookup.get(name_key(target))
            if gids:
                self.set_lookup.setdefault(name_key(alias), set()).update(gids)

    # ------------------------------------------------------------ parsing
    def parse(self, raw):
        """Split a title into clues and a name (dict shaped like Magic's)."""
        work = (raw or "").replace("’", "'")
        parsed = {"raw": raw, "game": self.game, "finish": "", "finish_explicit": False, "finish_words": set(),
                  "variant_terms": [], "serialized": False, "signed": bool(re.search(r"\bsigned\b", work, re.I)),
                  "set_groups": set(), "set_cues": [], "number": "", "language": "", "language_tokens": [],
                  "graded": False, "grader": "", "grade": "", "sealed": False, "set_product": False}
        parsed["row_condition"], work = extract_title_condition(work, NAME_WORDS.get(self.game, ()))

        g = GRADED_RE.search(work)
        if g or GRADED_WORD_RE.search(work):
            parsed["graded"] = True
            if g:
                parsed["grader"] = "BGS" if g.group(1).upper() == "BECKETT" else g.group(1).upper()
                parsed["grade"] = g.group(2)
        work = GRADED_WORD_RE.sub(" ", GRADED_RE.sub(" ", work))

        for token, lang in LANGUAGE_ALIASES.items():
            if token in self.set_abbrs:
                continue  # "POR" is a Pokémon set before it is Portuguese
            pat = r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])"
            if re.search(pat, work, re.I):
                if token in {"JP", "JPN", "JAP"} and re.search(r"\bJP\s+(?:alternate|alt)\s+art\b", work, re.I):
                    continue
                parsed["language"] = lang
                work = re.sub(pat, " ", work, flags=re.I)
        if not parsed["language"] and NON_LATIN_RE.search(work):
            parsed["language"] = "non-latin"

        for words in GAME_TITLE_WORDS.values():
            for w in words:
                work = re.sub(r"(?<![\w])" + re.escape(w) + r"(?![\w])", " ", work, flags=re.I)

        for pat in NUMBER_PATTERNS:
            m = pat.search(work)
            if m:
                parsed["number"] = m.group(1)
                work = work[:m.start()] + " " + work[m.end():]
                break

        tags = re.findall(r"\(([^()]*)\)|\[([^\[\]]*)\]", work)
        work = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", " ", work)
        tag_text = " ".join(a or b for a, b in tags)

        for pattern, words in FINISH_PHRASES:
            for src in ("tag", "work"):
                text = tag_text if src == "tag" else work
                m = re.search(pattern, text, re.I)
                if m:
                    parsed["finish_words"] |= words
                    if src == "work":
                        work = work[:m.start()] + " " + work[m.end():]
                    else:
                        tag_text = tag_text[:m.start()] + " " + tag_text[m.end():]
        if parsed["finish_words"]:
            parsed["finish_explicit"] = True

        # Set phrases: longest first, abbreviations only when written in capitals.
        def strip_sets(text):
            words = text.split()
            found = set()
            i = 0
            kept = []
            while i < len(words):
                hit = None
                for j in range(min(len(words), i + 8), i, -1):
                    chunk = words[i:j]
                    phrase = name_key(" ".join(chunk))
                    if phrase and phrase in self.set_lookup:
                        hit = (j, self.set_lookup[phrase])
                        break
                    if j == i + 1 and chunk[0].strip(",.;").upper() == chunk[0].strip(",.;") \
                            and "abbr:" + chunk[0].strip(",.;") in self.set_lookup:
                        hit = (j, self.set_lookup["abbr:" + chunk[0].strip(",.;")])
                        break
                if hit:
                    found |= hit[1]
                    i = hit[0]
                else:
                    kept.append(words[i])
                    i += 1
            return " ".join(kept), found

        def strip_variants(text):
            found = []
            for phrase in VARIANT_PHRASES:
                pat = r"(?<![\w'])" + re.escape(phrase) + r"(?![\w'])"
                if re.search(pat, text, re.I):
                    found.append(VARIANT_SYNONYMS.get(phrase, phrase))
                    text = re.sub(pat, " ", text, flags=re.I)
            return text, found

        # Sets before variants, so "Base Set Shadowless" is read as a set.
        tag_text, tag_variants = strip_variants(tag_text)
        variants = list(tag_variants)
        for t in [t.strip() for t in re.split(r"\s{2,}|,", tag_text) if t.strip()]:
            rest, groups = strip_sets(t)
            if groups and not rest.strip():
                parsed["set_groups"] |= groups
            else:
                variants.append(t)  # unknown tags still count as variant clues
        no_sets, groups = strip_sets(work)
        parsed["set_groups"] |= groups
        no_sets_no_variants, word_variants = strip_variants(no_sets)
        parsed["variant_terms"] = unique(variants + word_variants)
        parsed["set_cues"] = sorted({self.catalog.groups[g]["name"] for g in parsed["set_groups"]})

        def clean(text):
            return re.sub(r"\s+", " ", re.sub(r"(?:^|\s)[-–—,:|*]+(?=\s|$)", " ", text)).strip(" -,:|*")

        name = clean(no_sets_no_variants)
        # "Pikachu MEW 25": a bare trailing number next to a set is the card number.
        m = re.search(r"\s(\d{1,3}[a-z]?)$", name)
        if m and not parsed["number"] and (parsed["set_groups"] or self.by_core.get(name_key(name[:m.start()]))):
            parsed["number"] = m.group(1)
            name = name[:m.start()].strip()
        parsed["name"] = name
        # Readings where a stripped word was really part of the card name
        # ("Radiant Charizard", a card named like a set). The most specific
        # reading that is a real card name wins.
        parsed["name_options"] = unique([clean(no_sets), name, clean(strip_variants(work)[0]), clean(work)])
        return parsed

    # ----------------------------------------------------------- matching
    def _pick_subtype(self, product, parsed):
        """(subtype, price row, review) for the requested or default finish."""
        rows = product.get("prices") or {}
        priced = [s for s, r in rows.items() if choose_price(r)[0] is not None] or list(rows)
        if not priced:
            return "", None, ""
        want = parsed.get("finish_words") or set()
        if want:
            def words_of(s):
                w = set(norm(s).split())
                if "holofoil" in w:
                    w.add("foil")
                return w
            fits = [s for s in priced if want <= words_of(s) and ("reverse" in want or "reverse" not in words_of(s))]
            if not fits and want == {"holofoil"}:
                fits = [s for s in priced if "foil" in words_of(s) and "reverse" not in words_of(s)]
            if not fits and want == {"foil"}:
                fits = [s for s in priced if "holofoil" in words_of(s) and "reverse" not in words_of(s)]
            if fits:
                return fits[0], rows[fits[0]], ""
            review = f"REQUESTED FINISH NOT FOUND ({' '.join(sorted(want))})"
        else:
            review = ""
        order = ["Normal", "Unlimited", "Unlimited Holofoil", "Holofoil", "Foil", "Limited", "1st Edition",
                 "1st Edition Holofoil", "Reverse Holofoil"]
        choices = sorted(priced, key=lambda s: order.index(s) if s in order else len(order))
        pick = choices[0]
        editions = {s for s in priced if s.startswith(("1st Edition", "Unlimited"))}
        if not review and len(editions) >= 2 and not want:
            review = "ASSUMED EDITION (Unlimited)"
        return pick, rows[pick], review

    def price_range(self, products, parsed):
        vals = []
        for p in products:
            _s, row, _r = self._pick_subtype(p, parsed)
            v = choose_price(row)[0] if row else None
            if v is not None:
                vals.append(v)
        return (min(vals), max(vals)) if vals else (None, None)

    def candidates(self, parsed):
        """(products, match type) for the parsed title's name."""
        options = [o for o in parsed.get("name_options") or [parsed.get("name", "")] if self.by_core.get(name_key(o))]
        if options:
            best = max(options, key=lambda o: len(name_key(o)))
            if name_key(best) != name_key(parsed.get("name", "")):
                # Words kept in the name are no longer variant/set clues.
                kept = set(name_key(best).split())
                parsed["variant_terms"] = [v for v in parsed["variant_terms"] if not set(name_key(v).split()) <= kept]
                parsed["set_groups"] = {g for g in parsed["set_groups"]
                                        if not set(name_key(self.catalog.groups[g]["name"]).split()) <= kept}
            parsed["name"] = best
            return list(self.by_core[name_key(best)]), "EXACT"
        words = name_key(parsed.get("name", "")).split()
        by_number = self.by_number.get(number_key(parsed["number"]), []) if parsed.get("number") else []
        if by_number and not words:
            return list(by_number), "NUMBER"
        # A shortened name with a card number: "Ash Blossom RA01-EN008".
        if by_number and words:
            fit = [p for p in by_number if set(words) <= set(name_key(core_name(p["name"])).split())]
            if fit:
                return fit, "NUMBER"
        # Extra words before/after a real card name that describe the
        # printing ("Mirror Force Blue", "Holo Charizard"). Accepted only
        # when the product's tags, rarity or set confirm those words, so
        # "Lotus of the Abyss" never becomes a card called "Lotus".
        for size in range(len(words) - 1, 0, -1):
            for start in range(0, len(words) - size + 1):
                hits = self.by_core.get(" ".join(words[start:start + size]))
                if not hits:
                    continue
                extra = set(words[:start] + words[start + size:])
                fit = [p for p in hits
                       if extra <= set(name_key(" ".join([variant_text(p), p["name"], p["group_name"]])).split())]
                if fit:
                    parsed["name"] = " ".join(words[start:start + size])
                    parsed["variant_terms"] = unique(parsed["variant_terms"] + [" ".join(sorted(extra))])
                    return fit, "EXACT"
        # The start of exactly one card's name: "Ash Blossom" is
        # "Ash Blossom & Joyous Spring".
        if len(words) >= 2:
            head = " ".join(words) + " "
            longer = {k for k in self.names.by_token.get(words[0], ()) if k.startswith(head)}
            if len(longer) == 1:
                key = longer.pop()
                parsed["name"] = key
                return list(self.by_core[key]), "PARTIAL NAME"
        key, _ratio = self.names.fuzzy(parsed.get("name", ""))
        if key:
            return list(self.by_core[key]), "FUZZY"
        return [], "NO MATCH"

    def match(self, parsed):
        """Identify the printing. Returns a result dict for the engine."""
        cands, mtype = self.candidates(parsed)
        result = {"product": None, "subtype": "", "row": None, "match_type": mtype, "review": "",
                  "confidence": {"EXACT": 1.0, "NUMBER": 0.97, "PARTIAL NAME": 0.9, "FUZZY": 0.9}.get(mtype, 0.0),
                  "printings": 0, "low": None, "high": None}
        if not cands:
            result["review"] = "NO MATCH"
            return result
        if "code card" not in norm(parsed.get("raw", "")):
            cands = [p for p in cands if norm(p.get("rarity", "")) != "code card"] or cands

        notes = []
        related = []
        if parsed.get("set_groups"):
            in_set = [p for p in cands if p["group_id"] in parsed["set_groups"]]
            if in_set:
                # Sets named after this one ("Base Set (Shadowless)" for "Base
                # Set") stay in reserve: TCGplayer files 1st Edition Base Set
                # cards there, so a requested finish may only exist there.
                set_keys = [name_key(self.catalog.groups[g]["name"]) for g in parsed["set_groups"]]
                related = [p for p in cands if p["group_id"] not in parsed["set_groups"]
                           and any(name_key(p["group_name"]).startswith(k) for k in set_keys)]
                cands = in_set
                if len({p["group_id"] for p in cands}) > 1:
                    regular = [p for p in cands if "(" not in p["group_name"]]
                    if regular:
                        cands = regular
            else:
                notes.append("SET NOT FOUND FOR THIS CARD")
        if parsed.get("number"):
            key = number_key(parsed["number"])
            by_num = [p for p in cands if any(number_key(x) == key or number_key(x).split("/")[0] == key
                                              for x in re.split(r"\s*//\s*", p["number"] or ""))]
            if by_num:
                cands = by_num
            else:
                notes.append("NUMBER NOT FOUND FOR THIS CARD")
            # "OP01-016", "ST01-001", "LOB-005": the prefix is the set the
            # number belongs to. Reprints in decks / demo packs share the
            # number, so the original set wins unless another set was named.
            prefix = re.match(r"([A-Za-z]+\d*)-", parsed["number"])
            if prefix and not parsed.get("set_groups") and len(cands) > 1:
                code = prefix.group(1).lower()
                home = [p for p in cands if re.sub(r"[^a-z0-9]", "", p["group_abbr"].lower()) == code]
                if home:
                    cands = home
                    base = [p for p in cands if "(" not in p["group_name"]]
                    if base:
                        cands = base
        clues = [set(name_key(v).split()) for v in parsed.get("variant_terms") or []]
        if clues:
            def fits(p):
                words = set(name_key(" ".join([variant_text(p), p["name"], p["group_name"]])).split())
                if "parallel" in words:
                    words |= {"alternate", "art"}  # One Piece calls alt arts "Parallel"
                return all(c <= words for c in clues)
            fit = [p for p in cands if fits(p)]
            if len(fit) > 1:
                # "Secret Rare" means Secret Rare, not Quarter Century or
                # Platinum Secret Rare: keep the closest variant wording.
                wanted = set().union(*clues)
                def extra(p):
                    return len(set(name_key(" ".join(product_tags(p) + [p.get("rarity", "")])).split()) - wanted)
                least = min(extra(p) for p in fit)
                fit = [p for p in fit if extra(p) == least]
            if fit:
                cands = fit
            else:
                notes.append("VARIANT NOT CONFIRMED")
        else:
            # Without a variant word, the plain printing is meant, not the
            # alternate-art / manga / starlight version of the same number,
            # and the main-set card, not an event promo with the same number.
            if parsed.get("number") or parsed.get("set_groups"):
                plain = [p for p in cands if not product_tags(p)]
                if plain:
                    cands = plain
                not_promo = [p for p in cands if not is_promo(p)]
                if not_promo:
                    cands = not_promo
        if parsed.get("finish_words"):
            def has_finish(p):
                return not self._pick_subtype(p, parsed)[2].startswith("REQUESTED")
            with_finish = [p for p in cands if has_finish(p)] or [p for p in related if has_finish(p)]
            if with_finish:
                cands = with_finish

        cands = list({p["id"]: p for p in cands}.values())
        result["printings"] = len(cands)
        if len(cands) > 1:
            low, high = self.price_range(cands, parsed)
            result.update(low=low, high=high, review="; ".join(notes))
            result["candidates"] = cands
            return result
        product = cands[0]
        subtype, row, sub_review = self._pick_subtype(product, parsed)
        if mtype == "FUZZY":
            notes.insert(0, "FUZZY MATCH")
        if sub_review:
            notes.append(sub_review)
        result.update(product=product, subtype=subtype, row=row, review="; ".join(notes))
        return result


# ======================================================================
# cardpricer/listread.py
# ======================================================================

import csv
import io
import re
from pathlib import Path


ROLES = ("name", "quantity", "condition", "finish", "set", "number", "language", "game", "grade",
         "product_id", "rarity", "price", "ignore")

# Header words per role. Checked longest first so "set code" wins over "set".
HEADER_ALIASES = {
    "name": {"name", "card", "card name", "card names", "title", "titles", "input", "card list", "cards",
             "cards list", "product name", "product", "item", "item name", "description"},
    "quantity": {"quantity", "quantities", "qty", "count", "counts", "amount", "number owned", "copies",
                 "have", "owned", "total"},
    "condition": {"condition", "card condition", "cond"},
    "finish": {"foil", "foil?", "finish", "finishes", "foil status", "printing", "variance", "variant",
               "treatment", "holo", "edition type"},
    "set": {"set", "set name", "edition", "expansion", "set code", "edition code", "series", "release"},
    "number": {"collector number", "collector no", "collector #", "number", "card number", "cn", "card #",
               "card no", "no.", "#", "card id", "code"},
    "language": {"language", "lang", "card language"},
    "game": {"game", "category", "tcg", "product line"},
    "grade": {"grade", "graded", "grading", "slab"},
    "product_id": {"product id", "tcgplayer id", "tcgplayer product id", "tcg product id", "productid"},
    "rarity": {"rarity"},
    "price": {"price", "market price", "purchase price", "price each", "price bought", "my price", "low",
              "mid", "market", "average cost paid", "cost", "value", "total value", "price override"},
    "ignore": {"tradelist count", "trade quantity", "tags", "notes", "date added", "date bought", "last modified",
               "folder name", "portfolio name", "manabox id", "scryfall id", "sku", "simple name", "signed",
               "altered", "altered art", "misprint", "proxy", "alter", "promo", "textless", "artist proof",
               "printing id", "printing note", "watchlist", "purchase price currency", "binder name",
               "binder type", "location"},
}
# Roles that may appear in more than one column (set name + set code).
MULTI_ROLES = {"set", "price", "ignore"}

FINISH_WORDS = {"foil", "f", "yes", "y", "true", "etched", "etched foil", "nonfoil", "non-foil", "normal",
                "no", "n", "false", "holo", "holofoil", "reverse holo", "reverse holofoil", "reverse",
                "1st edition", "1st edition holofoil", "1st edition normal", "unlimited", "unlimited holofoil",
                "limited", "regular", "standard"}
GAME_WORDS = {"magic", "mtg", "magic: the gathering", "magic the gathering", "pokemon", "pokémon",
              "yugioh", "yu-gi-oh", "yu-gi-oh!", "ygo", "one piece", "one piece card game", "optcg",
              "riftbound", "riftbound league of legends trading card game"}
NUMBER_RE = re.compile(
    r"^(?:#?\d{1,4}[a-z]?(?:/\d{1,4})?"                  # 161, 025/165, #25, 12a
    r"|[a-z]{1,4}\d{1,4}(?:/[a-z]{0,4}\d{1,4})?"         # TG05/TG30, SWSH050, GG35, SVP044
    r"|[a-z0-9]{2,5}-[a-z]{0,2}\d{2,4}[a-z]?)$",         # LOB-EN001, OP01-120, OGN-001
    re.I)
PRICE_RE = re.compile(r"^\$?\s*\d{1,6}(?:,\d{3})*\.\d{2}$")

# "4 Lightning Bolt (LEB) 161 *F*"  (Moxfield / Arena / MTGO deck lists)
DECK_LINE_RE = re.compile(
    r"^(?P<qty>\d{1,3})x?\s+(?P<name>.+?)\s+\((?P<set>[A-Za-z0-9]{2,6})\)\s+(?P<num>[A-Za-z0-9\-]+)"
    r"(?P<foil>\s+\*[FE]\*)?\s*$")
# "Lightning Bolt x4"
TRAILING_QTY_RE = re.compile(r"^(?P<name>.+?)\s+[xX]\s?(?P<qty>\d{1,3})$")


# ---------------------------------------------------------------- file input
def _read_table(path):
    """Return the file as a list of rows (lists of strings)."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = [ln for ln in text.splitlines() if ln.strip()][:200]
    delimiter = None
    # The delimiter is the one most lines split into the same number of
    # fields with; title lines above a header may have none.
    best = 0
    for d in ("\t", ",", ";", "|"):
        counts = [len(next(csv.reader([ln], delimiter=d))) for ln in lines]
        multi = [c for c in counts if c >= 2]
        if not multi:
            continue
        mode = max(set(multi), key=multi.count)
        share = multi.count(mode) / len(lines)
        if share >= 0.5 and share > best:
            best, delimiter = share, d
    if delimiter is None:
        return [[line] for line in text.splitlines()]
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def _header_role(cell):
    n = norm(cell).strip(" :")
    for role in ("product_id", "ignore", "number", "set", "finish", "quantity", "condition", "language",
                 "game", "grade", "rarity", "price", "name"):
        if n in HEADER_ALIASES[role]:
            return role
    return None


def _find_header(rows):
    """Index of the header row within the first 10 rows, or None."""
    for i, row in enumerate(rows[:10]):
        cells = [c for c in row if c.strip()]
        hits = [c for c in cells if _header_role(c)]
        if len(hits) >= 2 or (len(hits) == 1 and len(cells) == 1 and _header_role(hits[0]) == "name"):
            return i
    return None


# ------------------------------------------------------------ role scoring
def _share(values, test):
    return sum(1 for v in values if test(v)) / len(values) if values else 0.0


def _is_quantity(v):
    v = v.strip().lower().rstrip("x").lstrip("x")
    return v.isdigit() and 0 < int(v) <= 999 and not (len(v) > 1 and v.startswith("0"))


def _score_column(values, known_name, known_set):
    """Score how well a column's values fit each role (0..1+)."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return {"ignore": 1.0}
    fill = len(vals) / len(values)
    distinct = len({v.lower() for v in vals})
    s = {}
    s["quantity"] = _share(vals, _is_quantity)
    ints = [int(v.strip().lower().strip("x")) for v in vals if _is_quantity(v)]
    if ints and sorted(ints)[len(ints) // 2] > 20:
        s["quantity"] *= 0.4  # big numbers are more likely collector numbers
    s["number"] = _share(vals, lambda v: bool(NUMBER_RE.match(v)) and not PRICE_RE.match(v))
    if s["number"] and any(re.search(r"[/\-]|^0\d|^[a-z]", v, re.I) for v in vals):
        s["number"] += 0.2
    s["price"] = _share(vals, lambda v: bool(PRICE_RE.match(v)))
    s["condition"] = _share(vals, lambda v: normalize_condition(v) is not None)
    s["finish"] = _share(vals, lambda v: norm(v) in FINISH_WORDS)
    s["language"] = _share(vals, lambda v: language_code(v) is not None and len(v) > 1)
    s["game"] = _share(vals, lambda v: norm(v) in GAME_WORDS)
    s["grade"] = _share(vals, lambda v: bool(re.match(r"^(?:psa|bgs|cgc|sgc|tag|beckett)\s*\d|^ungraded$|^raw$", v, re.I)))
    s["product_id"] = _share(vals, lambda v: v.isdigit() and len(v) >= 4) * 0.5
    alpha = _share(vals, lambda v: bool(re.search(r"[A-Za-z]{2}", v)) and not _is_number_only(v))
    avg_len = sum(len(v) for v in vals) / len(vals)
    s["set"] = _share(vals, known_set) if known_set else 0.0
    name_hits = _share(vals, known_name) if known_name else 0.0
    s["name"] = alpha * (0.5 + min(avg_len, 30) / 60) + name_hits
    # The name column is filled on (nearly) every row and varies: a mostly
    # empty "Foil?" column of the word "Foil" (also a card name) is not it.
    s["name"] *= fill
    if len(vals) >= 10 and distinct <= 3:
        s["name"] *= 0.3
    # A column of set names is not a name column even though it is text.
    if s["set"] > 0.6 and s["set"] > name_hits:
        s["name"] *= 0.3
    return s


def detect_roles(header, columns, known_name=None, known_set=None):
    """Assign one role to each column. Content decides; the header breaks ties
    and identifies roles content can't (price, ignore, product id)."""
    scores = []
    for idx, values in enumerate(columns):
        s = _score_column(values, known_name, known_set)
        hint = _header_role(header[idx]) if header and idx < len(header) else None
        if hint:
            s[hint] = s.get(hint, 0.0) + 0.45
        scores.append(s)

    roles = ["ignore"] * len(columns)
    taken = set()
    # Strongest fits first, so a clear quantity column can't be stolen by name.
    pairs = sorted(((sc, i, r) for i, s in enumerate(scores) for r, sc in s.items()), reverse=True)
    assigned = set()
    for sc, i, r in pairs:
        if i in assigned or sc < 0.5:
            continue
        if r in taken and r not in MULTI_ROLES:
            continue
        roles[i] = r
        assigned.add(i)
        taken.add(r)
    if "name" not in taken:
        # Fall back to the most text-like column that isn't numeric.
        best = max((i for i in range(len(columns)) if i not in assigned or roles[i] in MULTI_ROLES),
                   key=lambda i: scores[i].get("name", 0), default=None)
        if best is not None and scores[best].get("name", 0) > 0:
            roles[best] = "name"
    return roles


# --------------------------------------------------------------- one cell
def parse_list_line(text):
    """Pull structure out of a single free-text list line."""
    line = text.strip()
    m = DECK_LINE_RE.match(line)
    if m:
        return {"raw": m.group("name").strip(), "quantity": int(m.group("qty")), "set": m.group("set"),
                "collector": m.group("num"), "foil": "foil" if m.group("foil") else ""}
    m = TRAILING_QTY_RE.match(line)
    if m and not re.search(r"\b(?:psa|bgs|cgc|sgc)$", m.group("name"), re.I):
        return {"raw": m.group("name").strip(), "quantity": int(m.group("qty"))}
    name, qty = split_leading_quantity(line)
    return {"raw": name, "quantity": qty or 1}


def _quantity(value):
    v = (value or "").strip().lower().strip("x")
    try:
        return max(1, int(float(v)))
    except ValueError:
        return 1


def _blank_item(row_number):
    return {"condition": "", "foil": "", "set": "", "collector": "", "language": "", "game": "",
            "grade": "", "product_id": "", "rarity": "", "row_number": row_number}


def _free_text_items(lines, first_row_number):
    items = []
    for n, cell in enumerate(lines, start=first_row_number):
        if not cell or _is_number_only(cell):
            continue
        item = _blank_item(n)
        item.update(parse_list_line(cell))
        items.append(item)
    return items


# ------------------------------------------------------------------ public
def read_list(path, known_name=None, known_set=None):
    """Read a collection list. Returns (items, layout description).

    known_name / known_set are optional callables (text -> bool) used to
    recognize card-name and set-name columns by content.
    """
    rows = [[c.strip() for c in r] for r in _read_table(path)]
    rows = [r for r in rows if any(r)]
    if not rows:
        return [], "empty file"

    header_idx = _find_header(rows)
    header = rows[header_idx] if header_idx is not None else None
    body = rows[header_idx + 1:] if header_idx is not None else rows
    first_row_number = (header_idx + 2) if header_idx is not None else 1
    width = max(len(r) for r in body) if body else 0

    if width <= 1:
        return _free_text_items([r[0] if r else "" for r in body], first_row_number), \
            "one column: each line read as free text"

    columns = [[r[i] if i < len(r) else "" for r in body[:1000]] for i in range(width)]
    roles = detect_roles(header, columns, known_name, known_set)
    if "name" not in roles:
        return [], "no card-name column found"
    if header is None and set(roles) <= {"name", "ignore"}:
        # Nothing but text: commas inside names ("Ragavan, Nimble Pilferer")
        # split the lines, not real columns. Read each line whole.
        return _free_text_items([", ".join(c for c in r if c) for r in body], first_row_number), \
            "one column: each line read as free text"

    def col_label(i):
        letter = chr(ord("A") + i) if i < 26 else str(i + 1)
        return f"col {letter}" + (f" ({header[i]})" if header and i < len(header) and header[i] else "")

    layout = ", ".join(f"{r}={col_label(i)}" for i, r in enumerate(roles) if r not in ("ignore",))

    items = []
    for n, r in enumerate(body, start=first_row_number):
        get = {role: [] for role in ROLES}
        for i, role in enumerate(roles):
            if i < len(r) and r[i]:
                get[role].append(r[i])
        name = " ".join(get["name"]).strip()
        if not name or _is_number_only(name):
            continue
        if get["quantity"]:
            # A quantity column exists, so a leading number in the name
            # ("151 Booster Bundle") belongs to the name.
            item = {"raw": name, "quantity": _quantity(get["quantity"][0])}
        else:
            item = parse_list_line(name)
        finish = get["finish"][0] if get["finish"] else ""
        item.update({
            "condition": get["condition"][0] if get["condition"] else "",
            "foil": finish or item.get("foil", ""),
            "set": " | ".join(get["set"]) or item.get("set", ""),
            "collector": get["number"][0] if get["number"] else item.get("collector", ""),
            "language": get["language"][0] if get["language"] else "",
            "game": get["game"][0] if get["game"] else "",
            "grade": get["grade"][0] if get["grade"] else "",
            "product_id": get["product_id"][0] if get["product_id"] else "",
            "rarity": get["rarity"][0] if get["rarity"] else "",
            "row_number": n,
        })
        items.append(item)
    return items, layout


def extract_csv_rows(path, known_name=None, known_set=None):
    return read_list(path, known_name, known_set)[0]


# ======================================================================
# cardpricer/engine.py
# ======================================================================

import re
from collections import Counter


OUTPUT_COLUMNS = [
    "Status", "Game", "Input", "Quantity", "Matched Name", "Set", "Set Code", "Collector Number",
    "Finish", "Variant / Treatment", "Rarity", "Serialized", "Graded", "Grade",
    "Condition Assumption", "Condition Source", "Match Type", "Confidence", "Review Flag",
    "Market Price", "Condition Value", "Buy %", "Price Used", "Price Source", "Price Notes",
    "Extended Value", "Product ID", "TCGplayer URL", "Scryfall URL", "Image URL",
]

MANUAL_CHECK_PREFIX = "MANUAL CHECK"
GUESS = "__guess__"  # detect_game: no catalog knows this exact name
GAME_ORDER = ("magic", "pokemon", "yugioh", "onepiece", "riftbound")
STATUS_LABELS = {0: "GUARANTEED", 1: "NEEDS CHECKING", 2: "SEALED", 3: "MANUAL CHECK", 4: "UNPRICED", 5: "UNKNOWN"}

# Card numbers that only one game uses.
GAME_NUMBER_HINTS = [
    (re.compile(r"\b[A-Z0-9]{2,5}-(?:EN|E|DE|FR|IT|SP|PT|JP|KR|AE)[A-Z]?\d{2,3}\b"), "yugioh"),
    (re.compile(r"\b(?:OP|ST|EB|PRB)\d{2}-\d{3}\b", re.I), "onepiece"),
]


def manual_check_tags(parsed):
    """Rows that are never auto-priced and why."""
    tags = []
    if parsed.get("sealed_unmatched"):
        tags.append("SEALED PRODUCT")
    elif parsed.get("sealed_unpriced"):
        tags.append("SEALED PRODUCT (NO PRICE)")
    elif parsed.get("set_product"):
        tags.append("SET PRODUCT")
    if parsed.get("graded"):
        tags.append(" ".join(x for x in ("GRADED", parsed.get("grader"), parsed.get("grade")) if x))
    if parsed.get("language") and parsed.get("language") != "en":
        tags.append(f"FOREIGN ({parsed['language']})")
    if parsed.get("ambiguous"):
        tags.append("AMBIGUOUS PRINTING - needs set or number")
    return tags


def make_row(game, raw, qty, parsed, ident, review, condition, buy_tiers, condition_source="",
             special_rules=None, sealed_tiers=None):
    """Build one output row. ident describes the matched card/product (or is
    None) and carries its market price."""
    manual = manual_check_tags(parsed)
    if manual:
        review = f"{MANUAL_CHECK_PREFIX}: {', '.join(manual)}" + (("; " + review) if review else "")
    ident = ident or {}
    p = ident.get("price")
    source = ident.get("price_source", "")
    note = ident.get("price_note", "")
    cond_value = buy_pct = price_used = None
    if manual and ident.get("name"):
        reference = (f"Reference price {money_text(p)} (not used)" if p is not None
                     else ident.get("price_range") or "No reference price")
        note = f"Price manually: {', '.join(t.split(' (')[0].split(' - ')[0].lower() for t in manual)}. {reference}"
        p, source = None, ""
    if p is not None and ident.get("sealed"):
        _c, cond_value, buy_pct, price_used = price_offer(p, sealed_tiers or DEFAULT_SEALED_TIERS, None, (), {})
        condition = ""
        if buy_pct is not None:
            note += f"; sealed: {buy_pct:g}% buy range"
    elif p is not None:
        specials = ident.get("specials") or []
        all_cards = normalize_special_rules(special_rules).get("all")
        cond_pct, cond_value, buy_pct, price_used = price_offer(
            p, buy_tiers, condition, [r for _k, r in specials], all_cards)
        if cond_pct is not None:
            note += f"; {condition} = {cond_pct:g}% of NM -> {money_text(cond_value)}"
            plain_pct = price_offer(p, buy_tiers, condition, (), all_cards)[0]
            if cond_pct < plain_pct:
                labels = " + ".join(SPECIAL_RULE_LABELS[k] for k, _r in specials)
                note += f" ({labels} value used instead of {plain_pct:g}%)"
            if buy_pct is not None:
                note += f"; {buy_pct:g}% buy range"
    extended = price_used * qty if price_used is not None else None
    return {
        "Status": "",
        "Game": GAMES[game]["label"] if game in GAMES else "",
        "Input": raw,
        "Quantity": qty,
        "Matched Name": ident.get("name", ""),
        "Set": ident.get("set", ""),
        "Set Code": ident.get("set_code", ""),
        "Collector Number": ident.get("number", ""),
        "Finish": ident.get("finish", parsed.get("finish", "")),
        "Variant / Treatment": ", ".join(parsed.get("variant_terms") or []),
        "Rarity": ident.get("rarity", ""),
        "Serialized": "YES" if parsed.get("serialized") else "",
        "Graded": "YES" if parsed.get("graded") else "",
        "Grade": (parsed.get("grader", "") + " " + parsed.get("grade", "")).strip(),
        "Condition Assumption": condition,
        "Condition Source": condition_source if condition else "",
        "Match Type": ident.get("match_type", "NO MATCH"),
        "Confidence": f"{ident.get('confidence', 0.0):.0%}",
        "Review Flag": review,
        "Market Price": money_text(p),
        "Condition Value": money_text(cond_value) if not ident.get("sealed") else "",
        "Buy %": f"{buy_pct:.1f}%" if buy_pct is not None else "",
        "Price Used": money_text(price_used),
        "Price Source": source,
        "Price Notes": note.lstrip("; "),
        "Extended Value": money_text(extended),
        "Product ID": ident.get("product_id", ""),
        "TCGplayer URL": ident.get("tcgplayer_url", ""),
        "Scryfall URL": ident.get("scryfall_url", ""),
        "Image URL": ident.get("image", ""),
    }


# ------------------------------------------------------------------ columns
def _apply_common_columns(parsed, item):
    """Condition, grade and language columns, shared by every game."""
    condition = (item.get("condition") or "").strip()
    grade = (item.get("grade") or "").strip()
    language = (item.get("language") or "").strip()

    if grade and norm(grade) not in {"ungraded", "raw", "no", "none", "n/a", "-"}:
        m = GRADED_RE.search(grade)
        parsed["graded"] = True
        parsed["grader"] = m.group(1).upper() if m else parsed.get("grader", "")
        parsed["grade"] = m.group(2) if m else (grade if not parsed.get("grade") else parsed["grade"])
    if item.get("product_id"):
        parsed["product_id"] = str(item["product_id"]).strip()

    parsed["condition_source"] = "Title" if parsed.get("row_condition") else ""
    if condition:
        normalized = normalize_condition(condition)
        if normalized:
            parsed["row_condition"] = normalized
            parsed["condition_source"] = "CSV column"
        else:
            parsed.setdefault("parse_warnings", []).append(f"UNRECOGNIZED CONDITION '{condition}'")

    if language:
        code = language_code(language)
        if code:
            parsed["language"] = code
        else:
            parsed["language"] = language
            parsed.setdefault("parse_warnings", []).append(f"UNRECOGNIZED LANGUAGE '{language}'")
    return parsed


def _apply_row_indicators(parsed, item):
    """Magic: explicit columns are stronger than text inference (exports such
    as Title | Condition | Foil? keep finish/condition outside the title)."""
    _apply_common_columns(parsed, item)
    foil = norm(item.get("foil") or "")
    set_hints = [s.strip() for s in (item.get("set") or "").split(" | ") if s.strip()]
    collector_hint = (item.get("collector") or "").strip()

    if foil in {"normal", "nonfoil", "non-foil", "no", "n", "false", "0", "regular", "standard", "unlimited",
                "1st edition", "1st edition normal", "limited"}:
        parsed["finish"] = "nonfoil"
        parsed["finish_explicit"] = True
    elif foil in {"f", "yes", "y", "true"} or "foil" in foil or "holo" in foil or "etched" in foil:
        parsed["finish"] = "etched" if "etched" in foil else "foil"
        parsed["finish_explicit"] = True

    for set_hint in set_hints:
        parsed.setdefault("set_cues", []).append(set_hint)
    if collector_hint and re.fullmatch(r"\d{1,4}[A-Za-z]?", collector_hint):
        parsed["collector_number"] = collector_hint

    parsed["set_cues"] = unique(parsed.get("set_cues") or [])
    return parsed


def _apply_tcg_columns(parsed, item, matcher):
    """Other games: finish, set and number columns become matcher clues."""
    _apply_common_columns(parsed, item)
    finish = item.get("foil") or ""
    for pattern, words in FINISH_PHRASES:
        if re.search(pattern, finish, re.I):
            parsed["finish_words"] |= words
            parsed["finish_explicit"] = True
            break
    if norm(finish) in {"normal", "regular", "standard", "no", "false", "n"}:
        parsed["finish_words"] = {"normal"}
    for s in (item.get("set") or "").split(" | "):
        s = s.strip()
        if not s:
            continue
        groups = (matcher.set_lookup.get(name_key(s)) or matcher.set_lookup.get("abbr:" + s.upper())
                  or matcher.set_lookup.get("abbr:" + re.sub(r"[^A-Z0-9]", "", s.upper())))
        if groups:
            parsed["set_groups"] |= groups
    parsed["set_cues"] = sorted({matcher.catalog.groups[g]["name"] for g in parsed["set_groups"]})
    if item.get("collector"):
        parsed["number"] = item["collector"].strip()
    return parsed


def _item_key(item):
    """Rows with identical text and columns share one parse."""
    return tuple(sorted((k, str(v)) for k, v in item.items() if k not in ("quantity", "row_number")))


# --------------------------------------------------------------- the engine
class Engine:
    def __init__(self, magic_db=None, tcgcsv=None, log=print):
        self.magic_db = magic_db
        self.log = log
        self.matchers = {}
        catalogs = {}
        if tcgcsv is not None:
            for game in GAMES:
                cat = tcgcsv.catalog(game) if tcgcsv.has_data(game) else None
                catalogs[game] = cat
                if cat and game != "magic":
                    self.matchers[game] = TCGMatcher(game, cat)
        set_price_catalog(catalogs.get("magic"))
        self.sealed = SealedMatcher(catalogs) if any(catalogs.values()) else None
        self.games = [g for g in GAME_ORDER if (g == "magic" and magic_db) or g in self.matchers]

    # ---- vocabulary for the list reader
    def known_name(self, value):
        db = self.magic_db
        if db and (db.names.get(norm(value)) or db._compact_name_map.get(compact(value))):
            return True
        key = name_key(value)
        return any(key in m.by_core for m in self.matchers.values())

    def known_set(self, value):
        db = self.magic_db
        if db and (norm(value) in db._set_lookup or compact(value) in db._set_lookup):
            return True
        key = name_key(value)
        return any(key in m.set_lookup or "abbr:" + value.strip().upper() in m.set_lookup
                   for m in self.matchers.values())

    # ---- game detection
    def _magic_name_hit(self, raw):
        db = self.magic_db
        if not db:
            return False
        if db._embedded_exact_name(expand_card_name_shorthand(raw)):
            return True
        return bool(db.names.get(parse_dirty_title(raw)["name_norm"]))

    def _tcg_name_hit(self, game, raw):
        m = self.matchers[game]
        parsed = m.parse(raw)
        return any(m.by_core.get(name_key(o)) for o in parsed["name_options"])

    def name_hits(self, raw):
        return [g for g in self.games
                if (self._magic_name_hit(raw) if g == "magic" else self._tcg_name_hit(g, raw))]

    def explicit_game(self, item):
        """Game stated by a column, title words or a game-only card number."""
        texts = [item.get("game") or "", item.get("raw") or ""]
        for game, words in GAME_TITLE_WORDS.items():
            for text in texts:
                if any(re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text, re.I) for w in words):
                    return game
        if norm(item.get("game") or "") in {"magic", "mtg"}:
            return "magic"
        for pattern, game in GAME_NUMBER_HINTS:
            if pattern.search((item.get("raw") or "") + " " + (item.get("collector") or "")):
                return game
        return None

    def clear_game(self, item):
        """(game or None, name hits): the game when only one is possible."""
        explicit = self.explicit_game(item)
        if explicit and explicit in self.games:
            return explicit, [explicit]
        hits = self.name_hits(item["raw"])
        return (hits[0] if len(hits) == 1 else None), hits

    def detect_game(self, item, default_game, file_game=None, clear=None):
        """(game, note). A name found in several games, or in none (a typo),
        goes to the game most of the file is in; the screen's default game
        only decides when the file gives no hint."""
        game, hits = clear or self.clear_game(item)
        if game:
            return game, ""
        preferred = [g for g in (file_game, default_game) if g in self.games]
        if hits:
            game = next((g for g in preferred if g in hits), hits[0])
            others = ", ".join(GAMES[g]["label"] for g in hits if g != game)
            return game, f"GAME ASSUMED ({GAMES[game]['label']}; also a {others} name)"
        return (preferred[0] if preferred else self.games[0]), GUESS

    def guess_order(self, item, first):
        """Games to try for a name no catalog knows exactly (typos), the
        ones its card-number shape points to first."""
        text = (item.get("raw") or "") + " " + (item.get("collector") or "")
        hinted = []
        if re.search(r"\b[A-Za-z0-9]{2,5}-[A-Za-z]{0,3}\d{2,4}\b", text):
            hinted += ["yugioh", "onepiece"]
        if re.search(r"\d{1,3}[a-z]?\s?/\s?\d{2,3}\b", text):
            hinted += ["pokemon", "riftbound"]
        order = unique(hinted + [first] + list(self.games))
        return [g for g in order if g in self.games]

    def parse_for(self, game, item):
        raw = item["raw"]
        if game == "magic":
            parsed = _apply_row_indicators(parse_dirty_title(raw), item)
            db = self.magic_db
            parsed["set_cues"] = unique([db._set_lookup.get(norm(c)) or db._set_lookup.get(compact(c)) or c
                                         for c in parsed.get("set_cues") or []])
            return parsed
        return _apply_tcg_columns(self.matchers[game].parse(raw), item, self.matchers[game])

    def identify(self, game, item, parsed):
        if game == "magic":
            return self.identify_magic(item, parsed)
        return self.identify_tcg(game, parsed)

    def is_sealed(self, raw):
        if SEALED_RE.search(raw) or re.search(r"^\s*(?:complete\s+)?set\b|\bfactory\s+set\b", raw, re.I):
            return True
        return bool(TCG_SEALED_RE.search(raw)) and not self.name_hits(raw)

    # ---- per-game identification -> ident dict
    def identify_magic(self, item, parsed):
        db = self.magic_db
        cands, mtype = db.candidates(parsed)
        card, conf, review = choose_candidate(cands, parsed, mtype)
        if (card and not parsed.get("language") and card.get("lang") not in ("", "en")
                and norm(parsed.get("name", "")) == norm(card.get("printed_name", ""))
                and norm(parsed.get("name", "")) != norm(card.get("name", ""))):
            parsed["language"] = card["lang"]  # written with a foreign printed name
        cues = parsed.get("set_cues") or []
        if card and cues and not any(set_matches(card, c) for c in cues):
            # "Sheoldred" + DMU: the card in that set is "Sheoldred, the
            # Apocalypse". Use the one longer name printed in the named set.
            longer = self._magic_name_in_set(parsed.get("name", ""), cues)
            if longer:
                parsed["name"], parsed["name_norm"] = longer, norm(longer)
                card, conf, review = choose_candidate(db.names[norm(longer)], parsed, "NORMALIZED")
                mtype = "NORMALIZED"
                review = "; ".join(x for x in ("NAME COMPLETED FROM SET", review) if x)
            else:
                review = "; ".join(x for x in ("SET NOT FOUND FOR THIS CARD", review) if x)
        if not card:
            return None, (review if review and review != "NO MATCH" else "NO MATCH"), mtype
        price, source, note = price_card(card, parsed)
        product, _row = tcgplayer_product(card, parsed)
        if source.startswith("TCGplayer Low"):
            review = "; ".join(x for x in (review, "LOW PRICE ONLY (no market price)") if x)
        ident = {
            "name": matched_display_name(card, parsed), "set": card.get("set_name", ""), "set_code": card.get("set", ""),
            "number": card.get("collector_number", ""), "finish": effective_finish(card, parsed), "rarity": "",
            "match_type": mtype, "confidence": conf, "price": price, "price_source": source, "price_note": note,
            "product_id": product["id"] if product else (card.get("tcgplayer_id") or ""),
            "tcgplayer_url": product["url"] if product else "", "scryfall_url": card.get("scryfall_uri", ""),
            "image": image_url(card), "specials": special_rules_for(card, parsed, self._special_rules),
        }
        return ident, review, mtype

    def _magic_name_in_set(self, name, cues):
        """The one card whose name starts with name and is printed in a cue set."""
        db = self.magic_db
        words = norm(name).split()
        if not words:
            return None
        exact, loose = set(), set()
        wanted = {norm(c) for c in cues}
        for key in db._token_name_index.get(words[0], ()):
            if key.startswith(norm(name) + ",") or key.startswith(norm(name) + " "):
                cards = db.names.get(key, ())
                if any(norm(c.get("set_name", "")) in wanted or norm(c.get("set", "")) in wanted for c in cards):
                    exact.add(cards[0]["name"])
                elif any(set_matches(c, cue) for c in cards for cue in cues):
                    loose.add(cards[0]["name"])
        found = exact or loose
        return found.pop() if len(found) == 1 else None

    def identify_tcg(self, game, parsed):
        m = self.matchers[game]
        if parsed.get("product_id"):
            product = m.catalog.get(parsed["product_id"])
            if product:
                subtype, row, sub_review = m._pick_subtype(product, parsed)
                result = {"product": product, "subtype": subtype, "row": row, "match_type": "PRODUCT ID",
                          "confidence": 1.0, "review": sub_review}
            else:
                result = m.match(parsed)
        else:
            result = m.match(parsed)
        if result["product"] is None:
            if result.get("printings", 0) > 1:
                parsed["ambiguous"] = True
                low, high = result["low"], result["high"]
                rng = (f"{result['printings']} possible printings, {money_text(low)}-{money_text(high)}"
                       if low is not None else f"{result['printings']} possible printings")
                first = result["candidates"][0]
                ident = {"name": core_name(first["name"]),
                         "match_type": result["match_type"], "confidence": result["confidence"],
                         "price_range": rng}
                return ident, result["review"], result["match_type"]
            return None, result["review"] or "NO MATCH", result["match_type"]
        p = result["product"]
        price, basis = choose_price(result["row"])
        review = result["review"]
        if basis.startswith("TCGplayer Low"):
            review = "; ".join(x for x in (review, "LOW PRICE ONLY (no market price)") if x)
        ident = {
            "name": p["name"], "set": p["group_name"], "set_code": p["group_abbr"], "number": p["number"],
            "finish": result["subtype"], "rarity": p["rarity"], "match_type": result["match_type"],
            "confidence": result["confidence"], "price": price, "price_source": basis,
            "price_note": "Price from TCGplayer (TCGCSV)" if price is not None else "No TCGplayer price",
            "product_id": p["id"], "tcgplayer_url": p["url"], "image": p["image"],
        }
        return ident, review, result["match_type"]

    def identify_sealed(self, raw, game_hint):
        product, score, review, top = self.sealed.match(raw, [game_hint] if game_hint else None)
        if product is None:
            return None, review, top
        price, basis = choose_price(next(iter(product["prices"].values()), None))
        ident = {
            "name": product["name"], "set": product["group_name"], "set_code": product["group_abbr"],
            "finish": "", "match_type": "SEALED", "confidence": min(1.0, score), "price": price,
            "price_source": basis, "price_note": "Sealed price from TCGplayer (TCGCSV)" if price is not None
            else "No TCGplayer price", "product_id": product["id"], "tcgplayer_url": product["url"],
            "image": product["image"], "sealed": True, "game": product["game"],
        }
        return ident, review, top

    # ---- whole file
    def process_file(self, path, condition, buy_tiers, log, progress, special_rules=None, default_game="magic",
                     sealed_tiers=None):
        self._special_rules = special_rules
        items, layout = read_list(path, known_name=self.known_name, known_set=self.known_set)
        if not items:
            raise RuntimeError(f"No card rows were found in the input file ({layout}).")
        condition = normalize_condition(condition) or condition
        log(f"Found {len(items)} valid card rows.")
        log(f"Detected layout: {layout}")
        progress(0, len(items))
        totals = {"input": len(items), "exact": 0, "other": 0, "review": 0, "nomatch": 0,
                  "graded": 0, "with_price": 0, "value": 0.0}

        # Rows whose game is clear decide the file's main game; rows that
        # could be several games (or none) lean toward it.
        clear = {}
        sealed_keys = set()
        for item in items:
            key = _item_key(item)
            if key in clear or key in sealed_keys:
                continue
            if self.sealed and self.is_sealed(item["raw"]):
                sealed_keys.add(key)
            else:
                clear[key] = self.clear_game(item)
        votes = Counter(g for g, _hits in clear.values() if g)
        file_game = votes.most_common(1)[0][0] if votes else None
        if file_game:
            log(f"Main game of this list: {GAMES[file_game]['label']} "
                f"({votes[file_game]} of {sum(votes.values())} identifiable rows)")

        # Decide game and parse each distinct row once.
        plans = {}
        for item in items:
            key = _item_key(item)
            if key in plans:
                continue
            raw = item["raw"]
            if key in sealed_keys:
                plans[key] = {"game": self.explicit_game(item), "sealed": True, "note": ""}
                continue
            game, note = self.detect_game(item, default_game, file_game, clear[key])
            guessed = note == GUESS
            plans[key] = {"game": game, "sealed": False, "note": "" if guessed else note, "guessed": guessed,
                          "parsed": self.parse_for(game, item)}

        if self.magic_db:
            prewarm_fuzzy_multiprocess(self.magic_db, [p["parsed"] for p in plans.values()
                                                       if p.get("game") == "magic" and not p["sealed"]], log)

        output = []
        for i, item in enumerate(items, 1):
            raw = item["raw"]
            qty = int(item.get("quantity") or 1)
            plan = plans[_item_key(item)]
            log(f"[{i}/{len(items)}] {raw}  x{qty}")

            if plan["sealed"]:
                parsed = _apply_common_columns({"raw": raw, "variant_terms": []}, item)
                ident, review, top = self.identify_sealed(raw, plan["game"])
                game = (ident or {}).get("game") or plan["game"] or ""
                if ident is None:
                    parsed["sealed_unmatched"] = True
                    ident = {"match_type": "SEALED", "price_note": ("Closest: " + "; ".join(top)) if top else ""}
                elif ident.get("price") is None:
                    parsed["sealed_unpriced"] = True
                row = make_row(game, raw, qty, parsed, ident, review, "", buy_tiers, "", special_rules, sealed_tiers)
            else:
                game, parsed = plan["game"], plan["parsed"]
                row_condition = parsed.get("row_condition") or condition
                condition_source = parsed.get("condition_source") or "Default"
                if parsed.get("graded"):
                    totals["graded"] += 1
                ident, review, mtype = self.identify(game, item, parsed)
                if ident is None and plan.get("guessed"):
                    # No catalog had this exact name (usually a typo): try
                    # the other games before calling it unknown.
                    for other in [g for g in self.guess_order(item, game) if g != game]:
                        other_parsed = self.parse_for(other, item)
                        o_ident, o_review, o_mtype = self.identify(other, item, other_parsed)
                        if o_ident is not None:
                            game, parsed, ident, mtype = other, other_parsed, o_ident, o_mtype
                            review = "; ".join(x for x in (f"GAME GUESSED ({GAMES[other]['label']})", o_review) if x)
                            row_condition = parsed.get("row_condition") or condition
                            condition_source = parsed.get("condition_source") or "Default"
                            break
                extra = list(parsed.get("parse_warnings") or [])
                if plan["note"]:
                    extra.append(plan["note"])
                if parsed.get("signed"):
                    extra.append("SIGNED")
                review = "; ".join(unique(extra + ([review] if review else [])))
                if ident is None:
                    totals["nomatch"] += 1
                elif mtype == "EXACT":
                    totals["exact"] += 1
                else:
                    totals["other"] += 1
                row = make_row(game, raw, qty, parsed, ident, review, row_condition, buy_tiers, condition_source,
                               special_rules, sealed_tiers)
            if row["Review Flag"]:
                totals["review"] += 1
            output.append(row)
            progress(i, len(items))
            if row["Price Used"]:
                totals["with_price"] += 1
                numeric = money(row["Price Used"])
                if numeric is not None:
                    totals["value"] += numeric * qty

        for row in output:
            row["Status"] = STATUS_LABELS[_bucket(row)]
        # Confirmed rows on top, unknowns at the bottom; most valuable first
        # within each status.
        output.sort(key=lambda r: (_bucket(r), -(money(r["Price Used"]) or money(r["Market Price"]) or 0)))
        counts = {b: sum(1 for r in output if r["Status"] == STATUS_LABELS[b]) for b in STATUS_LABELS}
        log("Final audit: " + " | ".join(f"{STATUS_LABELS[b]}: {counts[b]}" for b in STATUS_LABELS))

        output.append({k: "" for k in OUTPUT_COLUMNS})
        summary = {k: "" for k in OUTPUT_COLUMNS}
        summary["Status"] = "TOTAL"
        summary["Input"] = "TOTAL"
        summary["Quantity"] = str(sum(int(x.get("quantity") or 1) for x in items))
        summary["Matched Name"] = f"{totals['with_price']} priced / {len(items)} rows"
        summary["Review Flag"] = f"{totals['review']} review"
        summary["Extended Value"] = f"${totals['value']:,.2f}"
        output.append(summary)
        return output, totals


def _bucket(row):
    mt = str(row.get("Match Type") or "").upper()
    matched = str(row.get("Matched Name") or "").strip()
    price = str(row.get("Price Used") or "").strip()
    review = str(row.get("Review Flag") or "").strip()
    if review.startswith(MANUAL_CHECK_PREFIX):
        return 3
    if mt == "SEALED" and price:
        return 2
    if not matched or mt == "NO MATCH":
        return 5
    if not price:
        return 4
    if review or mt not in {"EXACT", "NORMALIZED"}:
        return 1
    return 0


def process_file(path, db, condition, buy_tiers, log, progress, special_rules=None, tcgcsv=None,
                 default_game="magic", sealed_tiers=None, engine=None):
    """Price one list. Builds an Engine unless one is passed in."""
    engine = engine or Engine(db, tcgcsv, log)
    return engine.process_file(path, condition, buy_tiers, log, progress, special_rules, default_game, sealed_tiers)


# ======================================================================
# cardpricer/report.py
# ======================================================================

import csv


# Status -> fill color, top of the sheet to bottom.
STATUS_FILLS = {
    "GUARANTEED": "C6EFCE",      # green
    "NEEDS CHECKING": "FFEB9C",  # yellow
    "SEALED": "DDEBF7",          # blue
    "MANUAL CHECK": "F8CBAD",    # orange
    "UNPRICED": "E7E6E6",        # grey
    "UNKNOWN": "FFC7CE",         # red
}
MONEY_COLUMNS = {"Market Price", "Condition Value", "Price Used", "Extended Value"}
WIDTHS = {"Status": 15, "Game": 12, "Input": 40, "Matched Name": 36, "Set": 30, "Review Flag": 50,
          "Price Notes": 60, "TCGplayer URL": 30, "Scryfall URL": 30, "Image URL": 30}


def write_csv(rows, columns, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def write_xlsx(rows, columns, path):
    """Same rows as the CSV, with a filter on every column, the header frozen,
    one color per status and prices stored as numbers so they sort."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Priced"
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        values = []
        for col in columns:
            v = row.get(col, "")
            if col in MONEY_COLUMNS and v and money(v) is not None:
                v = money(v)
            elif col == "Quantity" and str(v).isdigit():
                v = int(v)
            values.append(v)
        ws.append(values)
        fill = STATUS_FILLS.get(row.get("Status", ""))
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill)
        if row.get("Status") == "TOTAL":
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
    for i, col in enumerate(columns, 1):
        letter = get_column_letter(i)
        ws.column_dimensions[letter].width = WIDTHS.get(col, max(10, min(18, len(col) + 2)))
        if col in MONEY_COLUMNS:
            for cell in ws[letter][1:]:
                cell.number_format = '"$"#,##0.00'
    last_data_row = 1 + sum(1 for r in rows if r.get("Status") not in ("", "TOTAL"))
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(2, last_data_row)}"
    ws.freeze_panes = "A2"
    wb.save(path)


# ======================================================================
# cardpricer/app.py
# ======================================================================

import json
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk


GAME_CHOICES = [(key, GAMES[key]["label"]) for key in ("magic", "pokemon", "yugioh", "onepiece", "riftbound")]


class TierTable:
    """Editable Min / Max / Buy % rows."""

    def __init__(self, parent, tiers):
        self.frame = ttk.Frame(parent)
        for col, text in enumerate(("Min price", "Max price", "Buy %")):
            ttk.Label(self.frame, text=text).grid(row=0, column=col, sticky="w", padx=(0, 8), pady=(0, 2))
        self.rows = []
        self._next_row = 1
        for tier in tiers:
            self.add(*tier[:3])

    def add(self, low="", high="", pct=""):
        r = self._next_row
        self._next_row += 1
        low_var = tk.StringVar(value="" if low is None else str(low))
        high_var = tk.StringVar(value="" if high is None else str(high))
        pct_var = tk.StringVar(value="" if pct is None else str(pct))
        widgets = [ttk.Entry(self.frame, textvariable=low_var, width=10),
                   ttk.Entry(self.frame, textvariable=high_var, width=10),
                   ttk.Entry(self.frame, textvariable=pct_var, width=8)]
        for col, w in enumerate(widgets):
            w.grid(row=r, column=col, sticky="w", padx=(0, 8), pady=1)
        row = (widgets, low_var, high_var, pct_var)
        remove = ttk.Button(self.frame, text="Remove", command=lambda: self.remove(row))
        remove.grid(row=r, column=len(widgets), sticky="w", pady=1)
        widgets.append(remove)
        self.rows.append(row)

    def remove(self, row):
        self.rows = [x for x in self.rows if x is not row]
        for w in row[0]:
            w.destroy()

    def reset(self, tiers):
        for row in list(self.rows):
            self.remove(row)
        for tier in tiers:
            self.add(*tier[:3])

    def values(self):
        return [[v.get().strip() for v in row[1:]] for row in self.rows]

    def tiers(self, label):
        """Validated tiers, or ValueError naming the table."""
        raw = [tuple(v) for v in self.values() if any(v)]
        clean = normalize_buy_tiers(raw)
        if len(clean) != len(raw):
            raise ValueError(f"{label}: every range needs a valid Min price, Buy %, and a Max above Min (or blank).")
        if not clean:
            raise ValueError(f"{label}: at least one price range is required.")
        for a, b in zip(clean, clean[1:]):
            if a[1] is None or a[1] > b[0]:
                raise ValueError(f"{label}: price ranges overlap. Make each range non-overlapping.")
        return clean


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Collection Pricer — Magic, Pokémon, Yu-Gi-Oh!, One Piece, Riftbound")
        self.geometry("1320x900")
        self.minsize(1000, 650)
        self.resizable(True, True)
        self.db = None
        self.tcgcsv = None
        self.engine = None
        self.busy = False
        self.events = queue.Queue()
        self.make_ui()
        self.after(100, self._drain_events)

    # ------------------------------------------------------------------ UI
    def make_ui(self):
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Collection Pricer", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")

        opts = ttk.LabelFrame(frame, text="Pricing assumptions", padding=10)
        opts.pack(fill="x")
        settings = self.load_settings()

        top = ttk.Frame(opts)
        top.grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="Condition assumption:").pack(side="left")
        self.condition = tk.StringVar(value=settings.get("condition") or "LP/MP")
        ttk.Combobox(top, textvariable=self.condition, values=["LP/MP", "NM", "LP", "MP", "HP", "DMG"],
                     state="readonly", width=8).pack(side="left", padx=(8, 4))
        ttk.Label(top, text="for rows with no condition (LP/MP averages LP and MP).").pack(side="left", padx=(0, 24))
        ttk.Label(top, text="Default game:").pack(side="left")
        labels = [label for _k, label in GAME_CHOICES]
        saved_game = dict(GAME_CHOICES).get(settings.get("default_game", "magic"), labels[0])
        self.default_game = tk.StringVar(value=saved_game)
        ttk.Combobox(top, textvariable=self.default_game, values=labels, state="readonly", width=20).pack(
            side="left", padx=(8, 4))
        ttk.Label(top, text="used when a name exists in several games or none.").pack(side="left")

        steps = ttk.Frame(opts)
        steps.grid(row=1, column=0, sticky="w", pady=(10, 0))

        step1 = ttk.LabelFrame(steps, text="Step 1 - Condition value (% of NM price)", padding=8)
        step1.grid(row=0, column=0, sticky="nw")
        for col, cond in enumerate(CONDITION_ORDER, start=1):
            ttk.Label(step1, text=cond).grid(row=0, column=col, sticky="w", padx=(0, 8))
        saved_special = settings.get("special_rules") or {}
        self.special_vars = {}
        for r, (key, label) in enumerate(SPECIAL_RULE_LABELS.items(), start=1):
            ttk.Label(step1, text=label).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=1)
            values = saved_special.get(key) or DEFAULT_SPECIAL_RULES[key]
            self.special_vars[key] = {}
            for col, cond in enumerate(CONDITION_ORDER, start=1):
                var = tk.StringVar(value=str(values.get(cond, "")))
                ttk.Entry(step1, textvariable=var, width=6).grid(row=r, column=col, sticky="w", padx=(0, 8), pady=1)
                self.special_vars[key][cond] = var
        ttk.Label(step1, text="Alpha/Beta/Unlimited and foil Magic cards use\ntheir row or All cards, whichever is lower.").grid(
            row=len(SPECIAL_RULE_LABELS) + 1, column=0, columnspan=len(CONDITION_ORDER) + 1, sticky="w", pady=(4, 0))

        ttk.Label(steps, text="→", font=("TkDefaultFont", 18)).grid(row=0, column=1, padx=10)

        step2 = ttk.LabelFrame(steps, text="Step 2 - Buy % (by condition value)", padding=8)
        step2.grid(row=0, column=2, sticky="nw")
        self.card_tiers = TierTable(step2, settings.get("tiers") or DEFAULT_BUY_TIERS)
        self.card_tiers.frame.pack(anchor="w")
        ttk.Button(step2, text="+ Add Price Range", command=lambda: self.card_tiers.add()).pack(anchor="w", pady=(6, 0))

        step3 = ttk.LabelFrame(steps, text="Sealed product - Buy % (no condition step)", padding=8)
        step3.grid(row=0, column=3, sticky="nw", padx=(24, 0))
        self.sealed_tiers = TierTable(step3, settings.get("sealed_tiers") or DEFAULT_SEALED_TIERS)
        self.sealed_tiers.frame.pack(anchor="w")
        ttk.Button(step3, text="+ Add Price Range", command=lambda: self.sealed_tiers.add()).pack(anchor="w", pady=(6, 0))

        reset_row = ttk.Frame(opts)
        reset_row.grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Button(reset_row, text="Reset Defaults", command=self.reset_defaults).pack(side="left")
        ttk.Label(reset_row, text="Example: $100 NM card in MP -> 70% = $70 condition value -> $70's Buy % applies. "
                                  "Leave Max blank for no upper limit. Settings are remembered between runs.").pack(
            side="left", padx=8)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=12)
        self.load_btn = ttk.Button(buttons, text="1. Load Card Data", command=self.load_data)
        self.load_btn.pack(side="left")
        self.file_btn = ttk.Button(buttons, text="2. Select List", command=self.select_file, state="disabled")
        self.file_btn.pack(side="left", padx=10)
        self.sync_btn = ttk.Button(buttons, text="Update TCGplayer Prices", command=self.update_prices)
        self.sync_btn.pack(side="left", padx=(30, 0))
        ttk.Label(buttons, text="TCGCSV refreshes once a day; a full update takes about 15 minutes.").pack(
            side="left", padx=8)

        self.progress_bar = ttk.Progressbar(frame, orient="horizontal", length=960, mode="determinate")
        self.progress_bar.pack(pady=(0, 10))
        self.status = ttk.Label(frame, text="Waiting. Click 1. Load Card Data to start.")
        self.status.pack(anchor="w")
        self.log_box = tk.Text(frame, height=30, width=120, state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

    # ------------------------------------------------------------ settings
    def load_settings(self):
        """Saved settings, upgraded to the current format; user values kept."""
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        except Exception:
            return {}
        return migrate_settings(settings)

    def save_settings(self):
        try:
            SETTINGS.write_text(json.dumps({
                "version": SETTINGS_VERSION,
                "condition": self.condition.get(),
                "default_game": self.game_key(),
                "special_rules": {k: {c: v.get().strip() for c, v in conds.items()}
                                  for k, conds in self.special_vars.items()},
                "tiers": self.card_tiers.values(),
                "sealed_tiers": self.sealed_tiers.values(),
            }, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"Could not save settings: {e}")

    def reset_defaults(self):
        self.card_tiers.reset(DEFAULT_BUY_TIERS)
        self.sealed_tiers.reset(DEFAULT_SEALED_TIERS)
        for key, conds in self.special_vars.items():
            for cond, var in conds.items():
                var.set(str(DEFAULT_SPECIAL_RULES[key].get(cond, "")))

    def game_key(self):
        return {label: key for key, label in GAME_CHOICES}.get(self.default_game.get(), "magic")

    def get_special_rules(self):
        raw = {k: {c: v.get().strip() for c, v in conds.items()} for k, conds in self.special_vars.items()}
        for key, conds in raw.items():
            for cond, value in conds.items():
                try:
                    if value and float(value) < 0:
                        raise ValueError
                except ValueError:
                    raise ValueError(f"{SPECIAL_RULE_LABELS[key]} {cond} value '{value}' must be a non-negative number or blank.")
        return normalize_special_rules(raw)

    # ------------------------------------------------- thread-safe updates
    def log(self, msg):
        self.events.put(("log", msg))

    def update_progress(self, value, total):
        self.events.put(("progress", (value, total)))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log_box.config(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.config(state="disabled")
                elif kind == "progress":
                    value, total = payload
                    self.progress_bar["maximum"] = max(1, total)
                    self.progress_bar["value"] = value
                    self.status.config(text=f"Working… {value:,} / {total:,}")
                elif kind == "status":
                    self.status.config(text=payload)
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def run_in_background(self, label, work, done=None):
        """Run work() on a worker thread; done(result) runs on the UI thread."""
        if self.busy:
            messagebox.showinfo("Busy", "Please wait for the current job to finish.")
            return
        self.busy = True
        for b in (self.load_btn, self.file_btn, self.sync_btn):
            b.config(state="disabled")
        self.events.put(("status", label))

        def runner():
            try:
                result, error = work(), None
            except Exception as e:  # reported on the UI thread
                result, error = None, e

            def finish():
                self.busy = False
                self.load_btn.config(state="normal")
                self.sync_btn.config(state="normal")
                self.file_btn.config(state="normal" if self.engine else "disabled")
                if error is not None:
                    self.log(f"ERROR: {error}")
                    self.status.config(text="Stopped with an error; see the log.")
                    messagebox.showerror("Error", str(error))
                elif done:
                    done(result)
            self.events.put(("call", finish))

        threading.Thread(target=runner, daemon=True).start()

    # ---------------------------------------------------------------- jobs
    def load_data(self):
        def work():
            db = ScryfallDB(self.log)
            db.ensure_bulk()
            db.build()
            tcg = TCGCSV(self.log)
            missing = [g for g in GAMES if not tcg.has_data(g)]
            if missing:
                self.log("TCGplayer data missing for: " + ", ".join(GAMES[g]["label"] for g in missing)
                         + ". Downloading now (one time, about 15 minutes for all games)...")
                tcg.sync(missing, self.update_progress)
            self.log("Indexing TCGplayer catalogs...")
            engine = Engine(db, tcg, self.log)
            return db, tcg, engine

        def done(result):
            self.db, self.tcgcsv, self.engine = result
            self.file_btn.config(state="normal")
            self.log("========================================")
            self.log("Card data ready: " + ", ".join(GAMES[g]["label"] for g in self.engine.games))
            self.status.config(text="Ready. Click 2. Select List.")

        self.run_in_background("Loading card data…", work, done)

    def update_prices(self):
        def work():
            tcg = self.tcgcsv or TCGCSV(self.log)
            changed = tcg.sync(list(GAMES), self.update_progress)
            engine = Engine(self.db, tcg, self.log) if (self.db and (changed or not self.engine)) else self.engine
            return tcg, engine, changed

        def done(result):
            self.tcgcsv, self.engine, changed = result
            self.log("TCGplayer prices updated." if changed else "TCGplayer prices were already current.")
            self.status.config(text="Ready." if self.engine else "Prices updated. Click 1. Load Card Data.")

        self.run_in_background("Updating TCGplayer prices…", work, done)

    def select_file(self):
        path = filedialog.askopenfilename(
            title="Select a card list",
            filetypes=[("Card lists", "*.csv *.tsv *.txt *.xlsx"), ("All files", "*.*")])
        if path:
            self.process(path)

    def process(self, path):
        if not self.engine:
            messagebox.showerror("Card data not loaded", "Click 1. Load Card Data first.")
            return
        try:
            buy_tiers = self.card_tiers.tiers("Step 2")
            sealed_tiers = self.sealed_tiers.tiers("Sealed product")
            special_rules = self.get_special_rules()
        except ValueError as e:
            messagebox.showerror("Invalid settings", str(e))
            return
        if buy_tiers[0][0] > 0:
            self.log("WARNING: No buy percentage is defined below $" + f"{buy_tiers[0][0]:,.2f}")
        self.save_settings()
        condition, default_game = self.condition.get(), self.game_key()

        def work():
            self.db.self_test()
            rows, totals = self.engine.process_file(path, condition, buy_tiers, self.log, self.update_progress,
                                                    special_rules, default_game, sealed_tiers)
            base = f"{os.path.splitext(path)[0]}_PRICED_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            write_csv(rows, OUTPUT_COLUMNS, base + ".csv")
            write_xlsx(rows, OUTPUT_COLUMNS, base + ".xlsx")
            return base + ".xlsx", totals

        def done(result):
            out, totals = result
            self.log("\n========================================")
            self.log("PROCESSING COMPLETE")
            self.log("========================================")
            self.log(f"Input rows:       {totals['input']}")
            self.log(f"Exact matches:    {totals['exact']}")
            self.log(f"Other matches:    {totals['other']}")
            self.log(f"Needs review:     {totals['review']}")
            self.log(f"No match:         {totals['nomatch']}")
            self.log(f"Graded:           {totals['graded']}")
            self.log(f"With price:       {totals['with_price']}")
            self.log(f"Extended value:   ${totals['value']:,.2f}")
            self.log(f"Output: {out}  (filterable, sorted by status; same rows in the .csv beside it)")
            self.status.config(text="Done.")
            messagebox.showinfo("Complete", f"Finished.\n\nOutput:\n{out}\n\nRows: {totals['input']}\n"
                                            f"Priced: {totals['with_price']}\nReview flagged: {totals['review']}\n"
                                            f"No match: {totals['nomatch']}")

        self.run_in_background("Pricing list…", work, done)


# ======================================================================
# Start
# ======================================================================
if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    App().mainloop()
