import time
import random
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os

app = FastAPI(title="Funny Affirmations (Reddit-powered)")

# Allow local dev + static file fetches
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Subreddits that often have one-liner “affirmations” / pickup-ish humor
SUBREDDITS = [
    "UnusualAffirmations",    # absurd positive statements
    "Affirmations",           # mix of serious and joke affirmations
    "PickupLines",            # cheesy or witty
    "clevercomebacks",        # quick witty replies
    "Showerthoughts",         # weird or deep short thoughts
    "Oneliners",              # pure short jokes
    "dadjokes",               # safe pun-heavy humor
    "punny",                  # puns and wordplay
    "contagiouslaughter",     # silly lines and fun moments
    "me_irl",                 # random self-deprecating jokes
    "rareinsults",            # creatively funny roasts
    "2meirl4meirl",           # surreal and absurd humor
    "firstworldanarchists",   # small harmless rebellion humor
    "funny",                  # general humor, needs filtering
]

# Cache (in-memory)
CACHE_TTL = 60 * 60  # 1 hour
_cache: Dict[str, Any] = {"items": [], "ts": 0}

USER_AGENT = "FunnyAffirmationsBot/0.1 (by u/your_username)"


def _looks_funny(text: str) -> bool:
    """Very light heuristic so we keep one-liner, funny-ish content."""
    if not text:
        return False
    if len(text) > 250:  # keep it snappy
        return False
    banned = ["suicide", "politics", "trigger"]
    low = text.lower()
    if any(b in low for b in banned):
        return False
    return True


async def fetch_subreddit_top(sub: str, limit=100, timeframe="month") -> List[Dict[str, Any]]:
    url = f"https://www.reddit.com/r/{sub}/top.json?t={timeframe}&limit={limit}"
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    posts = data.get("data", {}).get("children", [])
    cleaned: List[Dict[str, Any]] = []
    for p in posts:
        d = p.get("data", {}) or {}

        url_lower = (d.get("url_overridden_by_dest") or d.get("url") or "").lower()
        if (
            d.get("is_gallery")
            or d.get("post_hint") in {"image", "hosted:video", "rich:video", "link"}  # many media posts are tagged here
            or any(url_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".gifv", ".webm"])
        ):
            continue

        title = (d.get("title") or "").strip()
        selftext = (d.get("selftext") or "").strip()

        # Prefer short punchy titles; fall back to the first line of selftext
        line = title if _looks_funny(title) else (
            selftext.split("\n", 1)[0].strip() if _looks_funny(selftext) else ""
        )
        if not line:
            continue

        cleaned.append({
            "line": line,
            "permalink": f"https://www.reddit.com{d.get('permalink','')}",
            "subreddit": sub,
            "ups": d.get("ups", 0),
        })

    return cleaned


async def refresh_cache():
    global _cache
    now = time.time()
    if now - _cache["ts"] < CACHE_TTL and _cache["items"]:
        return  # still fresh

    # Rebuild cache
    all_items: List[Dict[str, Any]] = []

    # Fetch a bit from each subreddit; errors per-sub don’t kill the whole refresh
    for sub in SUBREDDITS:
        try:
            items = await fetch_subreddit_top(sub)
            all_items.extend(items)
        except Exception:
            # Soft-fail this subreddit
            continue

    # Deduplicate by text
    dedup: Dict[str, Dict[str, Any]] = {}
    for it in all_items:
        key = it["line"].lower()
        if key not in dedup or it.get("ups", 0) > dedup[key].get("ups", 0):
            dedup[key] = it

    _cache = {"items": list(dedup.values()), "ts": now}


@app.get("/")
async def root():
    # Serve the tiny frontend
    return FileResponse("static/index.html")


@app.get("/random")
async def random_affirmation():
    await refresh_cache()
    items = _cache["items"]
    if not items:
        raise HTTPException(status_code=503, detail="No affirmations available right now—try again soon.")
    item = random.choice(items)
    return JSONResponse(item)


@app.get("/healthz")
def healthz():
    return {"ok": True, "count": len(_cache.get("items", [])), "age_sec": time.time() - _cache.get("ts", 0)}
