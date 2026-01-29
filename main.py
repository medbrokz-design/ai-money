import os
import asyncio
import feedparser
import json
import httpx
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Bot
from supabase import create_client, Client
from google import genai
from google.genai import types

load_dotenv()

# Настройки
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OBSIDIAN_DB_PATH = r"D:\\Brain\\10_Projects\\AI_Money_Cases_Database"

# Инициализация клиентов
client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

async def is_duplicate(url: str) -> bool:
    if not supabase: return False
    try:
        res = supabase.table("ai_money_cases").select("url").eq("url", url).execute()
        return len(res.data) > 0
    except Exception:
        return False

async def fetch_hacker_news(client_http: httpx.AsyncClient):
    print("🔍 HN...")
    timestamp = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    query = "AI revenue OR AI profit OR AI SaaS OR AI MRR"
    url = f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&numericFilters=created_at_i>{timestamp}"
    found = []
    try:
        r = await client_http.get(url, timeout=10)
        if r.status_code == 200:
            for hit in r.json().get('hits', []):
                link = hit.get('url') or f"https://news.ycombinator.com/item?id={hit['objectID']}"
                if not await is_duplicate(link):
                    found.append({
                        'title': hit['title'],
                        'text': hit.get('story_text', '')[:2000],
                        'url': link,
                        'source': 'Hacker News'
                    })
    except Exception as e: print(f"❌ HN: {e}")
    return found

async def fetch_github(client_http: httpx.AsyncClient):
    print("🔍 GitHub...")
    date_str = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%Y-%m-%d')
    url = f"https://api.github.com/search/repositories?q=topic:ai+created:>{date_str}&sort=stars&order=desc"
    found = []
    try:
        r = await client_http.get(url, timeout=10)
        if r.status_code == 200:
            for item in r.json().get('items', [])[:10]:
                if not await is_duplicate(item['html_url']):
                    found.append({
                        'title': f"GH: {item['name']}",
                        'text': item['description'] or 'No description',
                        'url': item['html_url'],
                        'source': 'GitHub'
                    })
    except Exception as e: print(f"❌ GH: {e}")
    return found

async def fetch_reddit(client_http: httpx.AsyncClient):
    print("🔍 Reddit...")
    subreddits = ["SideProject", "SaaS", "Entrepreneur", "AiMoneyMaking", "IndieHackers", "solopreneur"]
    search_queries = ["AI revenue", "AI MRR", "AI profit", "AI case study"]
    found = []
    headers = {'User-Agent': 'Mozilla/5.0 (AI Money Bot 2.0)'}
    limit_date = datetime.now(timezone.utc) - timedelta(days=1)

    async def process_sub(sub):
        sub_found = []
        try:
            # Special handling for AiMoneyMaking (listing instead of search)
            urls = [f"https://www.reddit.com/r/{sub}/new.json?limit=10"] if sub == "AiMoneyMaking" else \
                   [f"https://www.reddit.com/r/{sub}/search.json?q={q}&sort=new&restrict_sr=1&limit=5" for q in search_queries]
            
            for url in urls:
                r = await client_http.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    for post in r.json().get('data', {}).get('children', []):
                        p = post['data']
                        if datetime.fromtimestamp(p['created_utc'], timezone.utc) > limit_date:
                            link = f"https://www.reddit.com{p['permalink']}"
                            if not await is_duplicate(link):
                                sub_found.append({
                                    'title': p['title'],
                                    'text': p.get('selftext', '')[:2000],
                                    'url': link,
                                    'source': f"Reddit (r/{sub})"
                                })
        except Exception as e: print(f"❌ Reddit {sub}: {e}")
        return sub_found

    results = await asyncio.gather(*(process_sub(s) for s in subreddits))
    for res in results: found.extend(res)
    return found

async def fetch_rss():
    print("🔍 RSS...")
    FEEDS = ["https://medium.com/feed/tag/ai-monetization", "https://www.indiehackers.com/rss"]
    found = []
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if pub_date > yesterday:
                        if not await is_duplicate(entry.link):
                            found.append({
                                'title': entry.title,
                                'text': entry.summary if 'summary' in entry else '',
                                'url': entry.link,
                                'source': 'RSS'
                            })
        except Exception as e: print(f"❌ RSS {url}: {e}")
    return found

def save_to_obsidian(case):
    try:
        safe_title = re.sub(r'[\\/*?:\"<>|]', "", case['title'])[:50]
        filename = f"{datetime.now().strftime('%Y-%m-%d')}_{safe_title}.md"
        filepath = os.path.join(OBSIDIAN_DB_PATH, filename)
        
        content = f"""
--- 
 type: ai-money-case
 date: {datetime.now().isoformat()}
 category: {case.get('category', 'Other')}
 profit: {case.get('profit_num', 0)}
 difficulty: {case.get('difficulty_score', 0)}
 source_url: {case['url']}
 tags: {case.get('tags', [])}
---
# {case['title']}

## 💰 Profit Description
{case['profit']}

## 🛠 Tech Stack
`{case['stack']}`

## 📝 Implementation Scheme
{case['scheme']}

## 🔗 Source
[{case['source']}]({case['url']})
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"📄 Obsidian: {filename}")
    except Exception as e: print(f"❌ Obsidian Save: {e}")

async def analyze_cases(cases):
    if not cases: return None, None
    context = "\n".join([f"SOURCE {i}: {c['title']} | URL: {c['url']} | TEXT: {c['text'][:1000]}" for i, c in enumerate(cases[:20])])

    prompt = f"""
    ANALYSIS TASK: Identify 2-3 REAL AI monetization cases from context. 
    
    CONTEXT:
    {context}

    JSON FORMAT:
    {{
      "telegram_post": "...",
      "cases": [
        {{
          "title": "...",
          "profit": "...",
          "profit_num": 1200,
          "category": "...",
          "tags": ["A", "B"],
          "difficulty_score": 1-10,
          "scheme": "Step-by-step",
          "stack": "Tools used",
          "url": "REAL_URL_FROM_CONTEXT",
          "source": "..."
        }}
      ]
    }}

    TELEGRAM RULES:
    - Title: 🔥 <b>КЕЙСЫ ЗАРАБОТКА: AI МОНЕТИЗАЦИЯ</b>
    - Short intro.
    - Per case:
      🚀 <b>Кейс: [Title]</b>
      💰 Профит: <i>[Profit]</i>
      📊 Сложность: [Difficulty 1-10, e.g. ▓▓▓░░░ 3/10]
      🛠 Стек: <code>[Stack]</code>
      📍 <a href="[URL]">Источник</a>
    - Divider & tags.
    """

    try:
        res = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(res.text)
        return data.get("telegram_post"), data.get("cases")
    except Exception as e: print(f"❌ AI Error: {e}")

async def main():
    print(f"🚀 Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    async with httpx.AsyncClient(follow_redirects=True) as client_http:
        tasks = [fetch_hacker_news(client_http), fetch_github(client_http), fetch_reddit(client_http), fetch_rss()]
        results = await asyncio.gather(*tasks)
    
    all_cases = [item for sublist in results for item in sublist]
    print(f"📊 New candidates: {len(all_cases)}")

    if all_cases:
        result = await analyze_cases(all_cases)
        if result and result[0]:
            report, cases_list = result
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=report, parse_mode='HTML', disable_web_page_preview=True)
            print("✉️ Telegram sent")
            
            if cases_list and supabase:
                for c in cases_list:
                    try:
                        supabase.table("ai_money_cases").upsert({**c, "created_at": datetime.now(timezone.utc).isoformat()}, on_conflict="url").execute()
                        save_to_obsidian(c)
                    except Exception as e: print(f"❌ Save error: {e}")
        else:
            print("⚠️ analyze_cases returned None (likely API error or no cases found).")
    else:
        print("📭 No new cases today.")

if __name__ == "__main__":
    asyncio.run(main())
