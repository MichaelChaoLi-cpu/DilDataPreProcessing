"""MICS Variable Alignment Tool — FastAPI backend."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent.parent.parent / ".env")

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
MODULES_DIR = APP_DIR.parent / "data" / "modules"
TRANSLATIONS_DIR = APP_DIR / "translations"
ALIGNMENT_PATH = APP_DIR / "alignment.yaml"
TRANSLATIONS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="MICS Variable Alignment")

# Per-module in-memory cache: module -> {ticker: info}
_module_cache: dict[str, dict] = {}


def _load_module(module: str) -> dict:
    if module not in _module_cache:
        path = MODULES_DIR / f"{module}.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            _module_cache[module] = yaml.safe_load(f) or {}
    return _module_cache[module]


def _available_modules() -> list[str]:
    return sorted(p.stem for p in MODULES_DIR.glob("*.yaml"))


# ── Alignment helpers ─────────────────────────────────────────────────────────

def _load_alignment() -> dict:
    if ALIGNMENT_PATH.exists():
        with open(ALIGNMENT_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_alignment(data: dict) -> None:
    with open(ALIGNMENT_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _mapped_keys(alignment: dict) -> set[tuple[str, str, int]]:
    keys: set[tuple[str, str, int]] = set()
    for info in alignment.values():
        for m in info.get("mappings", []):
            keys.add((m["module"], m["ticker"], m.get("label_idx", 0)))
    return keys


# ── Translation helpers ───────────────────────────────────────────────────────

def _translations_path(module: str) -> Path:
    return TRANSLATIONS_DIR / f"{module}.yaml"


def _load_translations(module: str) -> dict:
    path = _translations_path(module)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_translations(module: str, data: dict) -> None:
    with open(_translations_path(module), "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ── Variable row builder ──────────────────────────────────────────────────────

def _build_rows(module: str, mapped: set[tuple[str, str, int]], translations: dict) -> list[dict]:
    data = _load_module(module)
    result: list[dict] = []

    for ticker, info in data.items():
        labels = info.get("labels", [])
        global_rounds = info.get("rounds", [])
        ticker_trans = translations.get(ticker, {})

        if not labels:
            if (module, ticker, 0) not in mapped:
                result.append({
                    "module": module,
                    "ticker": ticker,
                    "label_idx": 0,
                    "text": "",
                    "translation": ticker_trans.get(0, ""),
                    "rounds": global_rounds,
                    "countries": [],
                })
            continue

        for label_idx, lb in enumerate(labels):
            if (module, ticker, label_idx) in mapped:
                continue
            text = lb.get("text", "")
            countries: list[str] = []
            seen_c: set[str] = set()
            label_rounds: list[str] = []
            seen_r: set[str] = set()
            for src in lb.get("sources", []):
                c = src.get("country", "")
                if c and c not in seen_c:
                    countries.append(c)
                    seen_c.add(c)
                r = src.get("round", "")
                if r and r not in seen_r:
                    label_rounds.append(r)
                    seen_r.add(r)
            result.append({
                "module": module,
                "ticker": ticker,
                "label_idx": label_idx,
                "text": text,
                "translation": ticker_trans.get(label_idx, ""),
                "rounds": label_rounds or global_rounds,
                "countries": countries,
            })

    return result


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/modules")
def list_modules() -> list[str]:
    return _available_modules()


@app.get("/api/variables")
def get_variables(module: Optional[str] = None) -> list[dict]:
    alignment = _load_alignment()
    mapped = _mapped_keys(alignment)
    modules = [module] if module else _available_modules()
    result: list[dict] = []
    for mod in modules:
        trans = _load_translations(mod)
        result.extend(_build_rows(mod, mapped, trans))
    return result


@app.get("/api/translations")
def get_translations(module: str) -> dict:
    return _load_translations(module)


@app.get("/api/alignment")
def get_alignment_api() -> dict:
    return _load_alignment()


@app.post("/api/alignment/var")
def create_var(body: dict) -> dict:
    name = (body.get("new_name") or "").strip()
    if not name:
        raise HTTPException(400, "new_name required")
    alignment = _load_alignment()
    if name not in alignment:
        alignment[name] = {"mappings": []}
    _save_alignment(alignment)
    return alignment


@app.post("/api/alignment/add")
def add_mapping(body: dict) -> dict:
    name = (body.get("new_name") or "").strip()
    tickers = body.get("tickers", [])
    if not name:
        raise HTTPException(400, "new_name required")
    alignment = _load_alignment()
    if name not in alignment:
        alignment[name] = {"mappings": []}
    existing = {
        (m["module"], m["ticker"], m.get("label_idx", 0))
        for m in alignment[name]["mappings"]
    }
    for t in tickers:
        key = (t["module"], t["ticker"], t.get("label_idx", 0))
        if key not in existing:
            alignment[name]["mappings"].append({
                "ticker": t["ticker"],
                "module": t["module"],
                "label_idx": t.get("label_idx", 0),
                "text": t.get("text", ""),
                "rounds": t.get("rounds", []),
            })
            existing.add(key)
    _save_alignment(alignment)
    return alignment


@app.delete("/api/alignment/var/{new_name}")
def delete_var(new_name: str) -> dict:
    alignment = _load_alignment()
    alignment.pop(new_name, None)
    _save_alignment(alignment)
    return alignment


@app.delete("/api/alignment/mapping/{new_name}/{module}/{ticker}/{label_idx}")
def delete_mapping(new_name: str, module: str, ticker: str, label_idx: int) -> dict:
    alignment = _load_alignment()
    if new_name in alignment:
        alignment[new_name]["mappings"] = [
            m for m in alignment[new_name]["mappings"]
            if not (
                m["module"] == module
                and m["ticker"] == ticker
                and m.get("label_idx", 0) == label_idx
            )
        ]
    _save_alignment(alignment)
    return alignment


@app.post("/api/translate")
async def translate_text(body: dict) -> dict:
    """Translate texts via Gemini and persist results."""
    items: list[dict] = body.get("items", [])  # [{module, ticker, label_idx, text}]
    if not items:
        return {"translations": []}

    sys.path.insert(0, str(APP_DIR))
    from llm import call_llm  # noqa: PLC0415

    texts = [it["text"] for it in items]
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = (
        "Translate the following variable label texts to English. "
        "Return only the translations, one per line, numbered in the same order. "
        "If a text is already English, return it unchanged.\n\n"
        f"{numbered}\n\nTranslations:"
    )
    raw = call_llm(prompt)
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    cleaned: list[str] = []
    for ln in lines:
        if ln and ln[0].isdigit():
            dot = ln.find(".")
            if dot != -1 and dot < 4:
                ln = ln[dot + 1:].strip()
        cleaned.append(ln)
    translations = cleaned[: len(items)]

    # Persist: group by module
    by_module: dict[str, dict] = {}
    for it, tr in zip(items, translations):
        mod = it["module"]
        if mod not in by_module:
            by_module[mod] = _load_translations(mod)
        ticker = it["ticker"]
        lidx = it.get("label_idx", 0)
        if ticker not in by_module[mod]:
            by_module[mod][ticker] = {}
        by_module[mod][ticker][lidx] = tr

    for mod, data in by_module.items():
        _save_translations(mod, data)

    return {"translations": translations}


@app.get("/api/alignment/export")
def export_yaml() -> Response:
    alignment = _load_alignment()
    content = yaml.dump(alignment, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=alignment.yaml"},
    )


# ── Static files (must be last) ───────────────────────────────────────────────
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
