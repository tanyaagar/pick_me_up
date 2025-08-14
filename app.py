import time
import random
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import asyncio

app = FastAPI(title="Funny Affirmations (Reddit-powered)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Subreddits that often have one-liner “affirmations” / pickup-ish humor
SUBREDDITS = [
    "UnusualAffirmations",    # absurd positive statements
    "PickupLines",            # cheesy or witty
    "Showerthoughts",         # weird or deep short thoughts
    "Oneliners",              # pure short jokes
    "punny",                  # puns and wordplay
    "contagiouslaughter",     # silly lines and fun moments
    "funny",                  # general humor, needs filtering
]

# Cache (in-memory)
FALLBACK_AFFIRMATIONS = [
    {
        "line": "You are as brilliant as a firefly in a jar, which is to say, you are a source of light in a confined space.",
        "permalink": "https://www.reddit.com/r/UnusualAffirmations/", "subreddit": "UnusualAffirmations", "ups": 1337,
    },
    {
        "line": "If you were a vegetable, you’d be a cute-cumber.",
        "permalink": "https://www.reddit.com/r/PickupLines/", "subreddit": "PickupLines", "ups": 9001,
    },
    {
        "line": "Your socks probably match right now. And if they don't, you're a rebel who can't be contained.",
        "permalink": "https://www.reddit.com/r/funny/", "subreddit": "funny", "ups": 5000,
    },
    # --- New affirmations added below ---
    {
        "line": "This is the equation of you: U = QT",
        "permalink": "https://www.reddit.com/r/PickupLines/", "subreddit": "PickupLines", "ups": 1500,
    },
    {
        "line": "If every time I thought of you a snowflake fell from the sky, we'd be in the middle of a blizzard.",
        "permalink": "https://www.reddit.com/r/PickupLines/", "subreddit": "PickupLines", "ups": 2500,
    },
    {
        "line": "I used to play piano by ear, but now I use my hands.",
        "permalink": "https://www.reddit.com/r/dadjokes/", "subreddit": "dadjokes", "ups": 1800,
    },
    {
        "line": "Why don’t skeletons fight each other? They don’t have the guts.",
        "permalink": "https://www.reddit.com/r/dadjokes/", "subreddit": "dadjokes", "ups": 2200,
    },
    {
        "line": "What did the janitor say when he jumped out of the closet? “Supplies!”",
        "permalink": "https://www.reddit.com/r/punny/", "subreddit": "punny", "ups": 1950,
    },
    {
        "line": "I’m reading a book on the history of glue. I just can’t seem to put it down.",
        "permalink": "https://www.reddit.com/r/dadjokes/", "subreddit": "dadjokes", "ups": 3100,
    },
]

# Cache (in-memory) - pre-populated with the expanded fallback list
CACHE_TTL = 60 * 60  # 1 hour
_cache: Dict[str, Any] = {"items": FALLBACK_AFFIRMATIONS, "ts": 0}



USER_AGENT = "F/0.1 (by u/my-cool-app)"


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
        return  
    tasks = [fetch_subreddit_top(sub) for sub in SUBREDDITS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_items: List[Dict[str, Any]] = []
    for res in results:
        # Check if a task failed and, if so, print the error and skip it
        if isinstance(res, Exception):
            print(f"--> Reddit fetch failed: {res}", file=sys.stderr) # 💡 ADD THIS LINE
            continue
        all_items.extend(res)
    dedup: Dict[str, Dict[str, Any]] = {}
    for it in all_items:
        key = it["line"].lower()
        if key not in dedup or it.get("ups", 0) > dedup[key].get("ups", 0):
            dedup[key] = it

    # 💡 FIX: Only update the cache if new items were actually fetched.
    new_items = list(dedup.values())
    if new_items:
        _cache = {"items": new_items, "ts": now}
    else:
        # If the fetch failed, keep the old data but update the timestamp
        # to prevent trying again on every single request.
        _cache["ts"] = now
    

@app.get("/")
async def root():
    # Serve the tiny frontend
    return FileResponse("index.html")


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
