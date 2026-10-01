import csv
import gzip
import json
import os
import pickle
import re
import unicodedata
import requests
import sys
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
import tkinter as tk
from pathlib import Path
from difflib import SequenceMatcher, get_close_matches
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

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
BULK_GZ = DATA_DIR / "scryfall_all_cards.jsonl.gz"
BULK_META = DATA_DIR / "bulk_metadata.json"
INDEX = DATA_DIR / "scryfall_index.pkl"
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
SEARCH_API = "https://api.scryfall.com/cards/search"
UA = {"User-Agent": "MTGCollectionBuyer/2.0 (personal collection pricing)"}
INDEX_VERSION = 17

SELF_TEST_NAMES = (
    "Mishra's Workshop",
    "Grim Monolith",
    "Black Lotus",
    "Primeval Titan",
)

OUTPUT_COLUMNS = [
    "Status", "Input", "Quantity", "Matched Name", "Set", "Set Code", "Collector Number",
    "Finish", "Variant / Treatment", "Serialized", "Graded", "Grade",
    "Condition Assumption", "Match Type", "Confidence", "Review Flag",
    "Scryfall Price", "Buy %", "Price Used", "Price Source", "Price Notes",
    "Extended Value", "Scryfall URL", "Image URL",
]

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
    m=re.match(r"^(\d+)\s*(?:[xX]\s+|\s+)(.+)$", text)
    if not m:
        return text, None
    qty=int(m.group(1))
    return (m.group(2).strip(), qty) if qty >= 1 else (text, None)


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


def _is_number_only(value):
    return bool(re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value or ""))


def _header_index(headers, aliases):
    normalized = {norm(h): i for i, h in enumerate(headers)}
    for alias in aliases:
        if norm(alias) in normalized:
            return normalized[norm(alias)]
    return None


def _looks_like_condition(value):
    n = norm(value)
    return n in {
        "nm", "near mint", "mint", "lp", "lightly played", "mp", "moderately played",
        "hp", "heavily played", "dmg", "damaged", "played", "excellent", "good",
    }


def _looks_like_foil_indicator(value):
    # IMPORTANT: bare numeric cells are never treated as foil indicators.
    # In headerless exports, 1/0 overwhelmingly means quantity or another
    # numeric field, and treating it as foil creates exactly the kind of
    # quantity/collector-number contamination this importer is designed to avoid.
    n = norm(value)
    return n in {"foil", "f", "yes", "y", "true", "etched", "etched foil",
                 "nonfoil", "normal", "no", "n", "false"}


def _infer_name_column(rows):
    """Choose one stable card-name column for a headerless CSV.

    We strongly prefer the column containing longer, title-like text and
    strongly penalize numeric, condition, and finish columns. Most importantly,
    this decision is made ONCE for the file: a bad row can never cause the
    importer to switch from the title column to a quantity column.
    """
    max_cols = max((len(r) for r in rows), default=0)
    if max_cols <= 1:
        return 0

    best_idx = 0
    best_score = float("-inf")
    sample = [r for r in rows[: min(len(rows), 1000)] if len(r) >= 2]
    if not sample:
        sample = rows[: min(len(rows), 1000)]

    for idx in range(max_cols):
        vals = [r[idx].strip() if idx < len(r) else "" for r in sample]
        nonempty = [v for v in vals if v]
        if not nonempty:
            continue
        numeric = sum(_is_number_only(v) for v in nonempty)
        conditions = sum(_looks_like_condition(v) for v in nonempty)
        foilish = sum(_looks_like_foil_indicator(v) for v in nonempty)
        alpha = sum(bool(re.search(r"[A-Za-z]", v)) for v in nonempty)
        longish = sum(len(v) >= 8 for v in nonempty)
        very_long = sum(len(v) >= 18 for v in nonempty)
        avg_len = sum(len(v) for v in nonempty) / len(nonempty)

        score = (
            alpha / len(nonempty) * 5.0
            + longish / len(nonempty) * 3.0
            + very_long / len(nonempty) * 8.0
            + min(avg_len, 60) / 20.0
            - numeric / len(nonempty) * 12.0
            - conditions / len(nonempty) * 9.0
            - foilish / len(nonempty) * 9.0
        )
        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


def extract_csv_rows(path):
    """Read dirty collection CSVs without confusing quantity for card name.

    Supported headered examples include:
      Title, Condition, Foil?
      Card Name, Quantity
      Name, Qty, Set, Collector Number, Finish

    Headerless files are also supported. A single stable card-name column is
    inferred for the entire file; numeric-only cells are NEVER promoted to card
    names. Explicit condition/foil/quantity/set/collector columns are retained
    as row indicators and applied later by the matcher.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        raw_rows = list(csv.reader(f))

    rows = [[c.strip() for c in r] for r in raw_rows if any(c.strip() for c in r)]
    if not rows:
        return []

    header_aliases = {
        "name": {"name", "card", "card name", "card names", "title", "titles", "input", "card list", "cards list"},
        "quantity": {"quantity", "quantities", "qty", "count", "counts", "amount", "number owned", "copies"},
        "condition": {"condition", "card condition", "cond"},
        "foil": {"foil", "foil?", "finish", "finishes", "foil status"},
        "set": {"set", "set name", "edition", "expansion", "set code", "edition code"},
        "collector": {"collector number", "collector no", "collector #", "number", "card number", "cn"},
    }
    first_norm = [norm(x) for x in rows[0]]
    has_header = any(x in header_aliases["name"] | header_aliases["quantity"] | header_aliases["condition"] | header_aliases["foil"] | header_aliases["set"] | header_aliases["collector"] for x in first_norm)

    result = []

    if has_header:
        headers = rows[0]
        name_idx = _header_index(headers, header_aliases["name"])
        qty_idx = _header_index(headers, header_aliases["quantity"])
        condition_idx = _header_index(headers, header_aliases["condition"])
        foil_idx = _header_index(headers, header_aliases["foil"])
        set_idx = _header_index(headers, header_aliases["set"])
        collector_idx = _header_index(headers, header_aliases["collector"])

        if name_idx is None:
            # Header exists, but does not explicitly identify the name column.
            # Infer it from the data rows rather than using first non-empty cell.
            name_idx = _infer_name_column(rows[1:]) if len(rows) > 1 else 0

        for row_number, r in enumerate(rows[1:], start=2):
            name = r[name_idx].strip() if name_idx < len(r) else ""
            # Critical safety rule: a blank/numeric name cell is not a card.
            # Do not fall back to another column; that is what produced the
            # screenshot's [250/2420] 2, 3, 1, 2, ... rows.
            if not name or _is_number_only(name):
                continue

            name, leading_qty = split_leading_quantity(name)
            qty_raw = r[qty_idx].strip() if qty_idx is not None and qty_idx < len(r) else ""
            if not qty_raw and leading_qty is not None:
                qty_raw = str(leading_qty)
            condition = r[condition_idx].strip() if condition_idx is not None and condition_idx < len(r) else ""
            foil = r[foil_idx].strip() if foil_idx is not None and foil_idx < len(r) else ""
            set_hint = r[set_idx].strip() if set_idx is not None and set_idx < len(r) else ""
            collector_hint = r[collector_idx].strip() if collector_idx is not None and collector_idx < len(r) else ""

            result.append({
                "raw": name,
                "quantity": max(1, int(float(qty_raw))) if _is_number_only(qty_raw) and float(qty_raw) >= 1 else 1,
                "condition": condition,
                "foil": foil,
                "set": set_hint,
                "collector": collector_hint,
                "row_number": row_number,
            })
        return result

    # Headerless: infer one name column globally.
    name_idx = _infer_name_column(rows)
    for row_number, r in enumerate(rows, start=1):
        name = r[name_idx].strip() if name_idx < len(r) else ""
        if not name or _is_number_only(name):
            # Never reinterpret another column as a card name.
            continue
        name, leading_qty = split_leading_quantity(name)

        # Strong common shape: Name | Quantity.
        qty = leading_qty or 1
        if len(r) >= 2:
            for idx in range(len(r) - 1, -1, -1):
                if idx == name_idx:
                    continue
                if _is_number_only(r[idx]):
                    qty = max(1, int(float(r[idx])))
                    break

        condition = next((x for i, x in enumerate(r) if i != name_idx and _looks_like_condition(x)), "")
        foil = next((x for i, x in enumerate(r) if i != name_idx and _looks_like_foil_indicator(x)), "")
        result.append({
            "raw": name,
            "quantity": qty,
            "condition": condition,
            "foil": foil,
            "set": "",
            "collector": "",
            "row_number": row_number,
        })
    return result


def parse_qty(v):
    try:
        return max(1, int(float(v)))
    except Exception:
        return 1


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

    sealed = bool(re.search(r"\bsealed\b|\bbooster\s+box\b|\bpremium\s+deck\s+series\b", work, re.I))
    set_product = bool(re.search(r"^\s*(?:complete\s+)?set\b|\bfactory\s+set\b", work, re.I))
    signed = bool(re.search(r"(?:^|[\s,*])signed\b", work, re.I))
    row_condition = ""
    condition_hits = re.findall(r"(?:^|[\s,*])(NM|LP|MP|HP|DMG|NEAR MINT|LIGHTLY PLAYED|MODERATELY PLAYED|HEAVILY PLAYED|DAMAGED)(?=\b|,)", work, re.I)
    if condition_hits:
        row_condition = condition_hits[-1].upper()

    language_aliases = {
        "JPN":"ja", "JP":"ja", "JAP":"ja", "TCH":"zht", "CHT":"zht",
        "SCH":"zhs", "CHS":"zhs", "ITL":"it", "ITA":"it", "GRM":"de",
        "GER":"de", "FRN":"fr", "FRE":"fr", "SPN":"es", "SPA":"es",
        "RUS":"ru", "KOR":"ko", "POR":"pt",
    }
    language = ""
    language_tokens = []
    for token, lang in language_aliases.items():
        if not re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", work, re.I):
            continue
        # In seller language, "JP Alternate Art" is a printing/treatment
        # descriptor, not a request to price a Japanese-language card.
        if token in {"JP", "JPN", "JAP"} and re.search(r"\bJP\s+(?:alternate|alt)\s+art\b", work, re.I):
            continue
        language = lang
        language_tokens.append(token)

    grader_m = re.search(r"\b(PSA|BGS|CGC|SGC)\s*(\d(?:\.\d+)?)\b", work, re.I)
    graded = bool(grader_m)
    grader = grader_m.group(1).upper() if grader_m else ""
    grade = grader_m.group(2) if grader_m else ""
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
    name = re.sub(r"\b(?:PSA|BGS|CGC|SGC)\s*\d(?:\.\d+)?\b", "", name, flags=re.I)
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

        for term in self.metadata_terms:
            self._metadata_lookup.setdefault(compact(term), term)

        for name in self.unique_names:
            cn = compact(name)
            if not cn:
                continue
            self._compact_name_map.setdefault(cn, []).append(name)
            # Parenthetical Scryfall names can be matched without scanning all
            # 500k+ names on every unresolved row.
            base = norm(re.sub(r"\s*\([^()]*\)\s*$", "", name))
            if base and base != norm(name):
                bcn = compact(base)
                if bcn:
                    self._compact_base_name_map.setdefault(bcn, []).append(name)
            self._length_name_index.setdefault(len(cn), []).append(name)
            for tok in set(re.findall(r"[a-z0-9]+", norm(name))):
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
        self.log(f"Persistent Scryfall data directory: {DATA_DIR}")
        self.log("Checking Scryfall bulk-data metadata...")
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
            self.log("Scryfall bulk file is current — no download needed.")
            return

        # If a user supplied an existing bulk file but no usable metadata, use it
        # rather than blindly downloading hundreds of MB. We record that the file
        # was locally adopted; the next launch will perform only the small metadata
        # request above and, if Scryfall has a newer updated_at, download once.
        if BULK_GZ.exists() and not old:
            self.log("Found existing local Scryfall bulk file without metadata — using it; no download needed.")
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

        self.log("Scryfall bulk file is missing or changed. Downloading fresh All Cards data...")
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
        self.log("Scryfall bulk download complete. Old index discarded.")

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
                self.log(f"Loaded {len(self.cards):,} Scryfall card records from persistent cache.")
                self.log("Scryfall bulk/index cache is valid — skipping full database rebuild.")
                self.self_test()
                return
            except Exception as e:
                self.log(f"Cached index rejected ({e}); rebuilding from bulk data...")

        self.log("No valid persistent index found. Building Scryfall search index (one-time/after Scryfall updates)...")
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
        self.log(f"Indexed {len(self.cards):,} Scryfall cards.")
        self.log("Saved Scryfall index cache.")

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
        source = parsed.get("raw", parsed.get("name", ""))
        source = re.sub(r"\([^()]*\)", " ", source)
        source = re.sub(r"\b(?:PSA|BGS|CGC|SGC)\s*\d(?:\.\d+)?\b", "", source, flags=re.I)
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
        for i in range(len(src_words)):
            for j in range(i + 1, min(len(src_words), i + max_set_words) + 1):
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
        self.log("Scryfall index self-test PASSED.")
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

    def _embedded_exact_name(self, raw):
        """Find the longest canonical name embedded in dirty text quickly."""
        cache_key = norm(raw)
        if cache_key in self._embedded_cache:
            return self._embedded_cache[cache_key]
        raw_c = compact(raw)
        if not raw_c:
            self._embedded_cache[cache_key] = None
            return None

        raw_tokens = [t for t in re.findall(r"[a-z0-9]+", cache_key) if len(t) >= 3]
        candidate_names = set()
        pools = []
        for tok in set(raw_tokens):
            hits = self._token_name_index.get(tok)
            if hits:
                pools.append((len(hits), hits))
        pools.sort(key=lambda x: x[0])
        for _, hits in pools[:4]:
            candidate_names.update(hits)

        best = None
        best_len = 0
        for name in candidate_names:
            cn = compact(name)
            if len(cn) >= 5 and cn in raw_c and len(cn) > best_len:
                best = name
                best_len = len(cn)
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
        qlen = len(qc)
        if len(pool) < 25:
            radius = max(2, min(6, qlen // 5))
            for ln in range(max(1, qlen-radius), qlen+radius+1):
                pool.update(self._length_name_index.get(ln, ()))

        if len(pool) > 2500:
            qset = set(qtokens)
            pool = set(sorted(pool, key=lambda k: (
                len(qset & set(re.findall(r"[a-z0-9]+", norm(k)))),
                -abs(len(compact(k))-qlen)
            ), reverse=True)[:2500])

        scored=[]
        qset=set(qtokens)
        for key in pool:
            kc=compact(key)
            if not kc:
                continue
            ratio=SequenceMatcher(None,qc,kc).ratio()
            kt=set(re.findall(r"[a-z0-9]+",norm(key)))
            overlap=len(qset & kt)/max(1,len(qset|kt))
            score=ratio*0.88+overlap*0.12
            scored.append((score,ratio,key))
        if not scored:
            result=(None,0.0,0.0)
            self._fuzzy_cache[q]=result
            return result
        scored.sort(reverse=True)
        best_score,best_ratio,best_key=scored[0]
        second_score=scored[1][0] if len(scored)>1 else 0.0
        margin=best_score-second_score
        min_ratio=0.84 if len(qc)>=8 else 0.88
        min_score=0.82 if len(qc)>=8 else 0.86
        if best_ratio>=min_ratio and best_score>=min_score and (margin>=0.025 or best_ratio>=0.94):
            result=(best_key,best_score,margin)
        else:
            result=(None,best_score,margin)
        self._fuzzy_cache[q]=result
        return result


    def candidates(self, parsed):
        embedded = self._embedded_exact_name(parsed.get("raw", ""))
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
        if not embedded:
            raw_words = re.findall(r"[A-Za-z0-9'’.-]+", parsed.get("name", ""))
            if len(raw_words) >= 3:
                for i in range(1, min(3, len(raw_words) - 1) + 1):
                    tail = " ".join(raw_words[i:]).strip()
                    if tail and tail.lower() != parsed.get("name", "").lower():
                        hits = self._name_hits(tail)
                        if hits:
                            parsed.setdefault("descriptor_terms", []).append(" ".join(raw_words[:i]))
                            return unique_cards(hits), "NORMALIZED"
        # 1. Exact canonical name is authoritative. Never let a Scryfall
        # search alias or fuzzy result replace an exact canonical card name.
        exact_hits = self.names.get(parsed["name_norm"], [])
        if exact_hits:
            return unique_cards(exact_hits), "EXACT"

        # 2. Normalized/base-name matches are allowed when Scryfall has a
        # parenthetical printing name (e.g. Chaos Emerald (Lotus Petal)).
        for name in parsed["name_variants"]:
            hits = self._name_hits(name)
            if hits:
                return unique_cards(hits), "NORMALIZED"

        # 3. Descriptor-prefix fallback. Collection lists often say things like
        # "Green Chaos Emerald" while the canonical Scryfall name is different.
        words = parsed["name"].split()
        for start in range(1, min(3, len(words)-1)+1):
            tail=" ".join(words[start:])
            if len(tail.split()) < 2:
                continue
            direct_tail=self._name_hits(tail)
            if direct_tail:
                parsed.setdefault("descriptor_terms", []).append(" ".join(words[:start]))
                return unique_cards(direct_tail), "NORMALIZED"

        # 4. CPU-heavy fuzzy matching, local only. No network request is made
        # here; unresolved names remain visible for manual review.
        fuzzy_name, fuzzy_score, fuzzy_margin = self._strict_fuzzy_name(parsed["name"])
        if fuzzy_name:
            hits=self._name_hits(fuzzy_name)
            if hits:
                parsed["resolved_name"]=fuzzy_name
                parsed["fuzzy_name_score"]=fuzzy_score
                parsed["fuzzy_name_margin"]=fuzzy_margin
                return unique_cards(hits), "FUZZY"
        return [], "NO MATCH"


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
    if "collector's edition" in sn or "collectors edition" in sn:
        return True
    if "international collector" in sn or "intl. collectors" in sn or "intl collectors" in sn:
        return True
    return False


def explicitly_requests_special_printing(parsed):
    text = norm(parsed.get("raw", ""))
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
    prices = card.get("prices") or {}
    finish = effective_finish(card, parsed)
    if finish == "foil":
        return money(prices.get("usd_foil")) is not None
    if finish == "etched":
        return money(prices.get("usd_etched")) is not None
    return money(prices.get("usd")) is not None

def _price_fallback_candidates(all_candidates, parsed, selected):
    """Find a priced sibling when the best printing has no Scryfall price.

    Strong identity clues are retained. An explicit set may be overridden only
    when the selected printing has no price and a sibling printing does; the
    caller marks that situation for review. Collector number is preferred as a
    cross-set clue, but is not required because collector numbers are set-local.
    """
    if not selected or _has_scryfall_price(selected, parsed):
        return []
    name_n = norm(selected.get("name", ""))
    pool = []
    for c in unique_cards(all_candidates):
        if norm(c.get("name", "")) != name_n:
            continue
        if not _card_has_requested_finish(c, parsed):
            continue
        if not parsed.get("serialized") and "serialized" in {norm(x) for x in (c.get("promo_types") or [])}:
            continue
        if not _has_scryfall_price(c, parsed):
            continue
        pool.append(c)

    if not pool:
        return []
    wanted_cn = norm(selected.get("collector_number", ""))
    same_cn = [c for c in pool if wanted_cn and collector_number_equal(c.get("collector_number", ""), wanted_cn)]
    return same_cn or pool


def _choose_priced_sibling(candidates, parsed):
    scored = []
    for c in candidates:
        sc = score_candidate(c, parsed)
        # Prefer the same collector number, then treatment/descriptor evidence,
        # then Scryfall price presence. Do not use price amount as a preference.
        same_cn = bool(parsed.get("collector_number") and collector_number_equal(c.get("collector_number", ""), parsed["collector_number"]))
        sc += 500 if same_cn else 0
        scored.append((sc, c))
    return max(scored, key=lambda x: x[0])[1] if scored else None


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
            money((c.get("prices") or {}).get("usd_foil" if effective_finish(c, parsed) == "foil" else "usd_etched" if effective_finish(c, parsed) == "etched" else "usd")),
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


def price_card(card, parsed):
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


def normalize_buy_tiers(tiers):
    """Normalize editable price bands. Each tier is (low, high, percent).
    high=None means no upper limit. Percent is a percentage such as 50 for 50%.
    """
    clean = []
    for low, high, pct in tiers:
        try:
            low = float(low)
            high = None if high in (None, "", "inf", "infinity") else float(high)
            pct = float(pct)
        except Exception:
            continue
        if low < 0 or (high is not None and high <= low) or pct < 0:
            continue
        clean.append((low, high, pct))
    clean.sort(key=lambda x: x[0])
    return clean


def buy_percent_for_price(price, tiers):
    """Return the buy percentage applicable to the source market price."""
    if price is None:
        return None
    for low, high, pct in normalize_buy_tiers(tiers):
        if price >= low and (high is None or price < high):
            return pct
    return None


def make_row(raw, qty, parsed, card, mtype, conf, review, condition, buy_tiers):
    if card:
        p, source, note = price_card(card, parsed)
        if parsed.get("language") and parsed.get("language") != "en":
            p = None
            source = ""
            note = "Foreign-language card: intentionally not priced"
            review = "FOREIGN CARD - UNPRICED" + (("; " + review) if review else "")
        if parsed.get("graded"):
            p = None
            source = ""
            note = "Graded card: no graded quote from Scryfall/TCGplayer"
        buy_pct = buy_percent_for_price(p, buy_tiers)
        price_used = p * (buy_pct / 100.0) if p is not None and buy_pct is not None else None
        extended = price_used * qty if price_used is not None else None
        variant = ", ".join(parsed["variant_terms"])
        return {
            "Status": "",
            "Input": raw,
            "Quantity": qty,
            "Matched Name": matched_display_name(card, parsed),
            "Set": card.get("set_name", ""),
            "Set Code": card.get("set", ""),
            "Collector Number": card.get("collector_number", ""),
            "Finish": effective_finish(card, parsed),
            "Variant / Treatment": variant,
            "Serialized": "YES" if parsed["serialized"] else "",
            "Graded": "YES" if parsed["graded"] else "",
            "Grade": (parsed["grader"] + " " + parsed["grade"]).strip(),
            "Condition Assumption": condition,
            "Match Type": mtype,
            "Confidence": f"{conf:.0%}",
            "Review Flag": review,
            "Scryfall Price": money_text(p),
            "Buy %": f"{buy_pct:.1f}%" if buy_pct is not None else "",
            "Price Used": money_text(price_used),
            "Price Source": source,
            "Price Notes": note,
            "Extended Value": money_text(extended),
            "Scryfall URL": card.get("scryfall_uri", ""),
            "Image URL": image_url(card),
        }

    return {
        "Status": "",
        "Input": raw, "Quantity": qty, "Matched Name": "", "Set": "", "Set Code": "",
        "Collector Number": "", "Finish": parsed["finish"],
        "Variant / Treatment": ", ".join(parsed["variant_terms"]),
        "Serialized": "YES" if parsed["serialized"] else "",
        "Graded": "YES" if parsed["graded"] else "",
        "Grade": (parsed["grader"] + " " + parsed["grade"]).strip(),
        "Condition Assumption": condition, "Match Type": mtype,
        "Confidence": f"{conf:.0%}", "Review Flag": review,
        "Scryfall Price": "", "Buy %": "", "Price Used": "", "Price Source": "",
        "Price Notes": "", "Extended Value": "", "Scryfall URL": "", "Image URL": "",
    }



# ============================================================
# Multiprocessing fuzzy resolver
# ============================================================
# IMPORTANT: workers never receive the 542k-card Scryfall database or the huge
# name/token indexes. The main process uses its already-built indexes to create
# a bounded candidate pool, then sends only the small pool for that query to a
# worker. This avoids the enormous spawn/pickle cost that made the prior
# "8-worker" implementation slower than single-process matching.

def _mp_fuzzy_score_one(job):
    q, candidates = job
    q = norm(q)
    qc = compact(q)
    if not qc:
        return q, None, 0.0, 0.0
    qtokens=[t for t in re.findall(r"[a-z0-9]+",q) if len(t)>=3]
    qset=set(qtokens)
    scored=[]
    for key in candidates:
        kc=compact(key)
        if not kc:
            continue
        ratio=SequenceMatcher(None,qc,kc).ratio()
        kt=set(re.findall(r"[a-z0-9]+",norm(key)))
        overlap=len(qset & kt)/max(1,len(qset|kt))
        score=ratio*0.88+overlap*0.12
        scored.append((score,ratio,key))
    if not scored:
        return q,None,0.0,0.0
    scored.sort(reverse=True)
    best_score,best_ratio,best_key=scored[0]
    second_score=scored[1][0] if len(scored)>1 else 0.0
    margin=best_score-second_score
    min_ratio=0.84 if len(qc)>=8 else 0.88
    min_score=0.82 if len(qc)>=8 else 0.86
    if best_ratio>=min_ratio and best_score>=min_score and (margin>=0.025 or best_ratio>=0.94):
        return q,best_key,best_score,margin
    return q,None,best_score,margin


def _fuzzy_candidate_pool(db, q):
    q=norm(q)
    qc=compact(q)
    if not qc:
        return []
    pool=set()
    qtokens=[t for t in re.findall(r"[a-z0-9]+",q) if len(t)>=3]
    for tok in qtokens:
        pool.update(db._token_name_index.get(tok,()))
    qlen=len(qc)
    if len(pool)<25:
        radius=max(2,min(6,qlen//5))
        for ln in range(max(1,qlen-radius),qlen+radius+1):
            pool.update(db._length_name_index.get(ln,()))
    if len(pool)>1200:
        qset=set(qtokens)
        pool=set(sorted(pool,key=lambda k:(
            len(qset & set(re.findall(r"[a-z0-9]+",norm(k)))),
            -abs(len(compact(k))-qlen)
        ),reverse=True)[:1200])
    return list(pool)


def _mp_score_chunk(jobs):
    """Score a chunk of (query, bounded candidate names) in one worker."""
    out = []
    for q, pool in jobs:
        out.append(_mp_fuzzy_score_one((q, pool)))
    return out


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


def _apply_row_indicators(parsed, item):
    """Apply explicit CSV columns after parsing the title.

    Explicit columns are stronger than text inference. This is especially
    important for exports such as Title | Condition | Foil?, where the title
    can be perfectly clean and the finish/condition live in separate columns.
    """
    condition = (item.get("condition") or "").strip()
    foil = norm(item.get("foil") or "")
    set_hint = (item.get("set") or "").strip()
    collector_hint = (item.get("collector") or "").strip()

    if condition:
        parsed["row_condition"] = condition

    if foil in {"foil", "f", "yes", "y", "true", "etched", "etched foil"}:
        parsed["finish"] = "etched" if foil.startswith("etched") else "foil"
        parsed["finish_explicit"] = True
    elif foil in {"normal", "nonfoil", "non-foil", "no", "n", "false", "0"}:
        parsed["finish"] = "nonfoil"
        parsed["finish_explicit"] = True

    if set_hint:
        parsed.setdefault("set_cues", []).append(set_hint)
    if collector_hint and re.fullmatch(r"\d{1,4}[A-Za-z]?", collector_hint):
        parsed["collector_number"] = collector_hint

    parsed["set_cues"] = unique(parsed.get("set_cues") or [])
    return parsed


def process_file(path, db, condition, buy_tiers, log, progress):
    items = extract_csv_rows(path)
    if not items:
        raise RuntimeError("No card rows were found in the input CSV.")

    log(f"Found {len(items)} valid card rows.")
    log("CSV parser: card-name and quantity roles were fixed for the entire file; numeric-only cells cannot become card names.")
    progress(0, len(items))
    output = []
    totals = {"input": len(items), "exact": 0, "other": 0, "review": 0, "nomatch": 0,
              "graded": 0, "with_price": 0, "value": 0.0}

    parsed_cache = {}
    for item in items:
        cache_key = (item["raw"], item.get("condition", ""), item.get("foil", ""), item.get("set", ""), item.get("collector", ""))
        if cache_key not in parsed_cache:
            parsed = parse_dirty_title(item["raw"])
            parsed = _apply_row_indicators(parsed, item)
            parsed_cache[cache_key] = parsed

    prewarm_fuzzy_multiprocess(db, list(parsed_cache.values()), log)

    for i, item in enumerate(items, 1):
        raw = item["raw"]
        if not raw or _is_number_only(raw):
            # This should be impossible after extract_csv_rows(), but keep the
            # invariant here so a malformed future importer can never send a
            # quantity/collector number into Scryfall as a card name.
            log(f"[{i}/{len(items)}] SKIPPED NON-CARD ROW: {raw!r}")
            progress(i, len(items))
            continue
        qty = int(item.get("quantity") or 1)
        cache_key = (raw, item.get("condition", ""), item.get("foil", ""), item.get("set", ""), item.get("collector", ""))
        parsed = parsed_cache[cache_key]
        row_condition = parsed.get("row_condition") or condition

        # Terminal output remains one row at a time, but explicitly shows the
        # quantity so a manager can immediately distinguish quantity from a
        # collector number embedded in the card title.
        log(f"[{i}/{len(items)}] {raw}  x{qty}")

        if parsed.get("sealed") or parsed.get("set_product"):
            totals["review"] += 1
            mtype = "SEALED PRODUCT" if parsed.get("sealed") else "SET PRODUCT"
            review = "SEALED PRODUCT - UNPRICED" if parsed.get("sealed") else "SET PRODUCT - UNPRICED"
            row = make_row(raw, qty, parsed, None, mtype, 1.0, review, row_condition, buy_tiers)
            output.append(row)
            progress(i, len(items))
            continue

        if parsed.get("graded"):
            totals["graded"] += 1

        cands, mtype = db.candidates(parsed)
        card, conf, review = choose_candidate(cands, parsed, mtype)

        if not card:
            totals["nomatch"] += 1
            totals["review"] += 1
            review = review if review and review != "NO MATCH" else "NO MATCH"
            if parsed.get("signed"):
                review = "SIGNED; " + review
            output.append(make_row(raw, qty, parsed, None, mtype, conf, review, row_condition, buy_tiers))
            progress(i, len(items))
            continue

        if mtype == "EXACT":
            totals["exact"] += 1
        else:
            totals["other"] += 1
        if review:
            totals["review"] += 1

        extra_review = []
        extra_review.extend(parsed.get("parse_warnings") or [])
        if parsed.get("signed"):
            extra_review.append("SIGNED")
        if extra_review:
            review = "; ".join(unique(extra_review + ([review] if review else [])))

        row = make_row(raw, qty, parsed, card, mtype, conf, review, row_condition, buy_tiers)
        output.append(row)
        progress(i, len(items))
        if row["Price Used"]:
            totals["with_price"] += 1
            numeric = money(row["Price Used"])
            if numeric is not None:
                totals["value"] += numeric * qty

    def _bucket(row):
        mt = str(row.get("Match Type") or "").upper()
        matched = str(row.get("Matched Name") or "").strip()
        price = str(row.get("Price Used") or "").strip()
        review = str(row.get("Review Flag") or "").strip()
        if mt in {"SEALED PRODUCT", "SET PRODUCT"}:
            return 2
        if not matched or mt == "NO MATCH":
            return 3
        if not price:
            return 2
        if review or mt not in {"EXACT", "NORMALIZED"}:
            return 1
        return 0

    labels = {0: "GUARANTEED", 1: "NEEDS CHECKING", 2: "UNPRICED", 3: "UNKNOWN"}
    for row in output:
        row["Status"] = labels[_bucket(row)]
    output.sort(key=_bucket)

    counts = {b: sum(1 for r in output if _bucket(r) == b) for b in range(4)}
    log("Final audit: " + " | ".join(f"{labels[b]}: {counts[b]}" for b in range(4)))

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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MTG Collection Pricer — Scryfall")
        self.geometry("1200x900")
        self.minsize(900, 650)
        self.resizable(True, True)
        self.db = None
        self.make_ui()

    def make_ui(self):
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="MTG Collection Pricer", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")

        opts = ttk.LabelFrame(frame, text="Pricing assumptions", padding=10)
        opts.pack(fill="x")

        ttk.Label(opts, text="Condition assumption:").grid(row=0, column=0, sticky="w")
        self.condition = tk.StringVar(value="LP/MP")
        ttk.Combobox(opts, textvariable=self.condition, values=["LP/MP", "LP", "MP", "NM"], state="readonly", width=10).grid(row=0, column=1, padx=8)
        ttk.Label(opts, text="Buy percentage is selected from the source market price:").grid(row=0, column=2, columnspan=4, sticky="w", padx=(20, 0))

        ttk.Label(opts, text="Min price").grid(row=1, column=0, sticky="w", pady=(8, 2))
        ttk.Label(opts, text="Max price").grid(row=1, column=1, sticky="w", pady=(8, 2))
        ttk.Label(opts, text="Buy %").grid(row=1, column=2, sticky="w", pady=(8, 2))

        self.tier_frame = ttk.Frame(opts)
        self.tier_frame.grid(row=2, column=0, columnspan=6, sticky="w")
        self.tier_rows = []
        default_tiers = [(0, 25, 50), (25, 100, 55), (100, 500, 60), (500, 1000, 65), (1000, None, 70)]
        for low, high, pct in default_tiers:
            self.add_tier_row(low, high, pct)

        tier_buttons = ttk.Frame(opts)
        tier_buttons.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Button(tier_buttons, text="+ Add Price Range", command=lambda: self.add_tier_row("", "", "")).pack(side="left")
        ttk.Button(tier_buttons, text="Reset Defaults", command=self.reset_tiers).pack(side="left", padx=8)
        ttk.Label(tier_buttons, text="Leave Max price blank for no upper limit.").pack(side="left", padx=8)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=12)
        self.load_btn = ttk.Button(buttons, text="1. Build / Verify Scryfall Database", command=self.load_db)
        self.load_btn.pack(side="left")
        self.file_btn = ttk.Button(buttons, text="2. Select Input CSV", command=self.select_file, state="disabled")
        self.file_btn.pack(side="left", padx=10)

        self.progress_bar = ttk.Progressbar(frame, orient="horizontal", length=960, mode="determinate")
        self.progress_bar.pack(pady=(0, 10))
        self.status = ttk.Label(frame, text="Waiting.")
        self.status.pack(anchor="w")
        self.log_box = tk.Text(frame, height=30, width=120, state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

    def add_tier_row(self, low="", high="", pct=""):
        row = ttk.Frame(self.tier_frame)
        row.pack(fill="x", pady=1)
        low_var = tk.StringVar(value="" if low is None else str(low))
        high_var = tk.StringVar(value="" if high is None else str(high))
        pct_var = tk.StringVar(value="" if pct is None else str(pct))
        ttk.Entry(row, textvariable=low_var, width=12).pack(side="left", padx=(0, 8))
        ttk.Entry(row, textvariable=high_var, width=12).pack(side="left", padx=(0, 8))
        ttk.Entry(row, textvariable=pct_var, width=10).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Remove", command=lambda r=row: self.remove_tier_row(r)).pack(side="left")
        self.tier_rows.append((row, low_var, high_var, pct_var))

    def remove_tier_row(self, row):
        self.tier_rows = [x for x in self.tier_rows if x[0] is not row]
        row.destroy()

    def reset_tiers(self):
        for row, *_ in self.tier_rows:
            row.destroy()
        self.tier_rows = []
        for low, high, pct in [(0, 25, 50), (25, 100, 55), (100, 500, 60), (500, 1000, 65), (1000, None, 70)]:
            self.add_tier_row(low, high, pct)

    def get_buy_tiers(self):
        tiers = []
        for _row, low_var, high_var, pct_var in self.tier_rows:
            low = low_var.get().strip()
            high = high_var.get().strip()
            pct = pct_var.get().strip()
            if not low and not high and not pct:
                continue
            tiers.append((low, high, pct))
        clean = normalize_buy_tiers(tiers)
        if not clean:
            raise ValueError("At least one valid buy-price range is required.")
        # Reject overlapping ranges because they make the selected buy percentage ambiguous.
        for a, b in zip(clean, clean[1:]):
            if a[1] is None or a[1] > b[0]:
                raise ValueError("Buy-price ranges overlap. Make each range non-overlapping.")
        if clean[0][0] > 0:
            self.log("WARNING: No buy percentage is defined below $" + f"{clean[0][0]:,.2f}")
        return clean

    def log(self, msg):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        self.update_idletasks()

    def update_progress(self, value, total):
        self.progress_bar["maximum"] = total
        self.progress_bar["value"] = value
        self.status.config(text=f"Processing {value:,} / {total:,}")
        self.update_idletasks()

    def load_db(self):
        self.load_btn.config(state="disabled")
        try:
            self.db = ScryfallDB(self.log)
            self.db.ensure_bulk()
            self.db.build()
            self.log("========================================")
            self.log("Scryfall database verified successfully.")
            self.log("The program will NOT proceed if the self-test fails.")
            self.file_btn.config(state="normal")
        except Exception as e:
            self.db = None
            self.log("DATABASE ERROR: " + str(e))
            messagebox.showerror("Scryfall Database Error", str(e))
        finally:
            self.load_btn.config(state="normal")

    def select_file(self):
        path = filedialog.askopenfilename(title="Select dirty card list CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.process(path)

    def process(self, path):
        if not self.db:
            messagebox.showerror("Database not ready", "Build/verify the Scryfall database first.")
            return
        try:
            buy_tiers = self.get_buy_tiers()
        except Exception as e:
            messagebox.showerror("Invalid buy ranges", str(e))
            return

        try:
            self.progress_bar["value"] = 0
            self.progress_bar["maximum"] = 1
            self.status.config(text="Starting processing…")
            self.update_idletasks()
            self.db.self_test()
            rows, totals = process_file(path, self.db, self.condition.get(), buy_tiers, self.log, self.update_progress)
            base = os.path.splitext(path)[0]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = f"{base}_PRICED_{stamp}.csv"

            with open(out, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
                w.writeheader()
                w.writerows(rows)

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
            self.log(f"Output: {out}")
            self.log("Review rows are flagged in the Review Flag column of the same CSV; no separate review file was created.")
            messagebox.showinfo("Complete", f"Finished.\n\nOutput:\n{out}\n\nRows: {totals['input']}\nPriced: {totals['with_price']}\nReview flagged: {totals['review']}\nNo match: {totals['nomatch']}")
        except Exception as e:
            self.log("PROCESSING ERROR: " + str(e))
            messagebox.showerror("Processing Error", str(e))


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
