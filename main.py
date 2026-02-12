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
_keys_raw = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_API_KEYS = [k.strip() for k in _keys_raw.split(",") if k.strip()]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OBSIDIAN_DB_PATH = r"D:\Brain\10_Projects\AI_Money_Cases_Database"

# Инициализация клиентов
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

async def is_duplicate(url: str) -> bool:
    if not supabase: return False
    try:
        res = supabase.table("ai_money_cases").select("url").eq("url", url).execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"⚠️ Supabase error: {e}")
        return False

async def fetch_hacker_news(client_http: httpx.AsyncClient):
    print("🔍 HN...")
    timestamp = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    query = "AI revenue OR AI profit OR AI SaaS OR AI MRR"
    url = f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&numericFilters=created_at_i>{timestamp}"
    found = []
    try:
        r = await client_http.get(url, timeout=15)
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
        r = await client_http.get(url, timeout=15)
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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    limit_date = datetime.now(timezone.utc) - timedelta(days=7)

    async def process_sub(sub):
        sub_found = []
        try:
            urls = [f"https://www.reddit.com/r/{sub}/new.json?limit=25"] if sub == "AiMoneyMaking" else \
                   [f"https://www.reddit.com/r/{sub}/search.json?q={q}&sort=new&restrict_sr=1&limit=10" for q in search_queries]
            
            for url in urls:
                r = await client_http.get(url, headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and 'data' in data:
                        for post in data.get('data', {}).get('children', []):
                            p = post['data']
                            text = p.get('selftext', '')
                            title = p.get('title', '')
                            combined = (title + " " + text).lower()
                            
                            if any(k in combined for k in ["$", "revenue", "mrr", "profit", "earned", "made", "income"]):
                                if datetime.fromtimestamp(p['created_utc'], timezone.utc) > limit_date:
                                    link = f"https://www.reddit.com{p['permalink']}"
                                    if not await is_duplicate(link):
                                        sub_found.append({
                                            'title': p['title'],
                                            'text': text[:3000],
                                            'url': link,
                                            'source': f"Reddit (r/{sub})"
                                        })
                elif r.status_code == 429:
                    print(f"⚠️ Reddit {sub} rate limited (429)")
                else:
                    print(f"⚠️ Reddit {sub} status {r.status_code}")
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
    if not os.path.exists(OBSIDIAN_DB_PATH):
        print(f"ℹ️ Obsidian path not found, skipping save: {OBSIDIAN_DB_PATH}")
        return
    try:
        safe_title = re.sub(r'[\\/*?:"<>|]', "", case['title'])[:50]
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

def build_telegram_report(cases):
    if not cases: return ""
    
    report = "💎 <b>AI MONEY CASES: ЕЖЕДНЕВНЫЙ РАЗБОР</b>\n"
    report += "<i>Прагматичный взгляд на то, где сейчас лежат деньги в ИИ.</i>\n\n"
    
    for c in cases:
        score = c.get('difficulty_score', 5)
        filled = "🟢" * (score // 2)
        empty = "⚪" * (5 - (score // 2))
        bar = f"{filled}{empty}"
        
        report += f"🚀 <b>{c['title'].upper()}</b>\n"
        report += f"💰 <b>Профит:</b> {c['profit']}\n"
        report += f"🛠 <b>Стек:</b> <code>{c['stack']}</code>\n"
        report += f"⚙️ <b>Сложность:</b> {bar} ({score}/10)\n\n"
        
        report += f"📝 <b>КАК ЭТО РАБОТАЕТ:</b>\n{c['scheme']}\n\n"
        
        if 'insight' in c:
            report += f"💡 <b>ПОЧЕМУ ЭТО 'ТЕМКА':</b>\n<i>{c['insight']}</i>\n\n"
        
        report += f"📍 <a href=\"{c['url']}\">Читать первоисточник</a>\n"
        report += "────────────────────\n\n"
    
    report += "🎯 <b>Действуй или наблюдай.</b>\n"
    report += "#AI #MoneyCases #SaaS #Automation"
    return report

async def analyze_cases(cases):
    if not cases: return None
    context = "\n".join([f"CASE_ID {i}: TITLE: {c['title']} | URL: {c['url']} | CONTENT: {c['text'][:2500]}" for i, c in enumerate(cases[:20])])

    prompt = f"""
    ROLE: Senior Business Analyst & Digital Entrepreneur.
    TASK: Extract ALL high-quality, REAL, and QUANTIFIABLE AI monetization cases from the context below (up to 10 cases).
    
    CRITICAL RULES:
    1. ONLY use cases with specific numbers (revenue, profit, users).
    2. IGNORE general questions, ads, or vague stories.
    3. Return "source_id" matching exactly the CASE_ID from context.
    4. Be extremely skeptical. Look for actual execution details.
    5. Translate all descriptive fields (scheme, insight) into Russian.
    6. If you find multiple cases, keep each description concise.

    CONTEXT:
    {context}

    JSON FORMAT:
    [
      {{
        "source_id": 0,
        "title": "Short descriptive title",
        "profit": "E.g. $450/week",
        "profit_num": 450,
        "category": "SaaS/Marketing/etc",
        "tags": ["A", "B"],
        "difficulty_score": 1-10,
        "scheme": "Brief step-by-step logic (in Russian)",
        "stack": "Tools used",
        "insight": "Short explanation why this is a good opportunity (in Russian)"
      }}
    ]
    """

    if not GEMINI_API_KEYS:
        print("❌ No Gemini API keys found in environment.")
        return None

    for key in GEMINI_API_KEYS:
        for model_name in ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-flash-latest"]:
            try:
                print(f"🤖 AI Analysis with key: {key[:8]}... (Model: {model_name})")
                client_ai = genai.Client(api_key=key)
                res = client_ai.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                
                # Чистка текста от возможных markdown-оберток
                text = res.text.strip()
                if text.startswith("```json"): text = text[7:-3].strip()
                elif text.startswith("```"): text = text[3:-3].strip()
                
                raw_cases = json.loads(text)
                
                final_cases = []
                for rc in raw_cases:
                    idx = rc.get("source_id")
                    if idx is not None and 0 <= idx < len(cases):
                        rc["url"] = cases[idx]["url"]
                        rc["source"] = cases[idx]["source"]
                        final_cases.append(rc)
                return final_cases
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(f"⚠️ {model_name} quota exceeded. Trying next...")
                    continue
                else:
                    print(f"❌ AI Error with {model_name}: {e}")
                    continue
    
    return None

async def main():
    print(f"🚀 Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN is not set.")
        return

    async with httpx.AsyncClient(follow_redirects=True) as client_http:
        tasks = [fetch_hacker_news(client_http), fetch_github(client_http), fetch_reddit(client_http), fetch_rss()]
        results = await asyncio.gather(*tasks)
    
    all_cases = [item for sublist in results for item in sublist]
    print(f"📊 New candidates for analysis: {len(all_cases)}")

    if all_cases:
        cases_list = await analyze_cases(all_cases)
        if cases_list:
            fresh_cases = []
            if supabase:
                for c in cases_list:
                    if not await is_duplicate(c['url']):
                        fresh_cases.append(c)
            else:
                fresh_cases = cases_list

            if not fresh_cases:
                print("📭 No fresh unique cases after filtering.")
                return

            report = build_telegram_report(fresh_cases)
            try:
                bot = Bot(token=TELEGRAM_BOT_TOKEN)
                async with bot:
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=report, parse_mode='HTML', disable_web_page_preview=True)
                print("✉️ Telegram sent")
            except Exception as e:
                print(f"❌ Telegram send error: {e}")
            
            if supabase:
                safe_columns = {'title', 'profit', 'profit_num', 'category', 'scheme', 'stack', 'url', 'source', 'difficulty_score', 'tags', 'insight'}
                for c in fresh_cases:
                    try:
                        db_case = {k: v for k, v in c.items() if k in safe_columns}
                        supabase.table("ai_money_cases").upsert({**db_case, "created_at": datetime.now(timezone.utc).isoformat()}, on_conflict="url").execute()
                        save_to_obsidian(c)
                    except Exception as e: print(f"❌ Database/Obsidian Save error: {e}")
        else:
            print("⚠️ analyze_cases returned no results (API error or filtering).")
    else:
        print("📭 No new cases found in sources today.")


if __name__ == "__main__":
    asyncio.run(main())
