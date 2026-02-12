import os
import asyncio
import feedparser
import json
import httpx
import re
import trafilatura
import urllib.parse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
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
PROJECTS_MOC_PATH = r"D:\Brain\10_Projects\10_Projects_MOC.md"

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

async def deep_scrape(url: str) -> str:
    """Извлекает полный текст статьи по ссылке, если это не соцсеть."""
    if any(x in url for x in ["reddit.com", "github.com", "t.me"]):
        return ""
    try:
        print(f"🌐 Scrapping: {url}...")
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            content = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            return content[:5000] if content else ""
    except Exception as e:
        print(f"⚠️ Scrape error {url}: {e}")
    return ""

def get_project_context():
    """Собирает контекст наших текущих ресурсов для 'Brain Sync'."""
    try:
        if os.path.exists(PROJECTS_MOC_PATH):
            with open(PROJECTS_MOC_PATH, "r", encoding="utf-8") as f:
                content = f.read()
                # Извлекаем только список активных проектов
                projects = re.findall(r"\[\[(.*?)\]\]", content)
                return ", ".join(projects[:15])
    except: pass
    return "Telegram Parser, WhatsApp Bot, Nano Banana Pro (AI Prompts), SEO Automation"

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
                    text = hit.get('story_text', '')
                    if not text: # Если текста нет, пробуем парсить ссылку
                        text = await deep_scrape(link)
                    
                    found.append({
                        'title': hit['title'],
                        'text': text[:4000],
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
    FEEDS = [
        "https://medium.com/feed/tag/ai-monetization",
        "https://www.indiehackers.com/rss",
        "https://news.google.com/rss/search?q=AI+SaaS+revenue+case+study&hl=en-US",
        "https://www.producthunt.com/feed"
    ]
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
                            text = entry.get('summary', '')
                            # Если это внешняя статья, пробуем глубокий парсинг
                            if len(text) < 500:
                                deep_text = await deep_scrape(entry.link)
                                if deep_text: text = deep_text

                            found.append({
                                'title': entry.title,
                                'text': text[:5000],
                                'url': entry.link,
                                'source': f"RSS ({urllib.parse.urlparse(url).netloc})"
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
    if not cases: return "", None
    
    report = "💎 <b>AI PROFIT BLUEPRINT: РАЗБОР КЕЙСА</b>\n"
    report += "────────────────────\n"
    
    for c in cases:
        score = c.get('difficulty_score', 5)
        filled = "●" * (score // 2)
        empty = "○" * (5 - (score // 2))
        bar = f"{filled}{empty}"
        
        report += f"🚀 <b>{c['title'].upper()}</b>\n\n"
        report += f"💰 <b>ПРОФИТ:</b> <code>{c['profit']}</code>\n"
        report += f"📊 <b>КАТЕГОРИЯ:</b> #{c.get('category', 'SaaS').replace(' ', '_')}\n"
        report += f"⚙️ <b>СЛОЖНОСТЬ:</b> {bar} ({score}/10)\n\n"
        
        report += "📝 <b>МЕХАНИКА (STEP-BY-STEP):</b>\n"
        scheme = c['scheme']
        if not scheme.startswith('•'):
            scheme = "\n".join([f"  • {line.strip()}" for line in scheme.split('\n') if line.strip()])
        report += f"<i>{scheme}</i>\n\n"
        
        report += f"🛠 <b>СТЕК ТЕХНОЛОГИЙ:</b>\n<code>{c['stack']}</code>\n\n"
        
        if 'insight' in c:
            report += f"💡 <b>РЫЧАГ МОНЕТИЗАЦИИ:</b>\n<i>{c['insight']}</i>\n\n"
        
        report += f"📍 <a href=\"{c['url']}\"><b>ОТКРЫТЬ ПЕРВОИСТОЧНИК</b></a>\n"
        report += "────────────────────\n\n"
    
    report += "🎯 <b>Действуй или наблюдай.</b>\n"
    report += "#AI #MoneyCases #SaaS #BuildInPublic"

    # Интерактивные кнопки (админ-панель)
    keyboard = [
        [
            InlineKeyboardButton("📥 Сохранить всё", callback_data="save_all"),
            InlineKeyboardButton("📊 Тренды недели", callback_data="get_trends")
        ],
        [
            InlineKeyboardButton("🚀 Запустить MVP бота", url="https://t.me/TeleFocusBot")
        ]
    ]
    
    return report, InlineKeyboardMarkup(keyboard)

async def analyze_cases(cases):
    if not cases: return None
    our_projects = get_project_context()
    context = "\n".join([f"CASE_ID {i}: TITLE: {c['title']} | URL: {c['url']} | SOURCE: {c['source']} | CONTENT: {c['text'][:4000]}" for i, c in enumerate(cases[:12])])

    prompt = f"""
    ROLE: Senior Digital Entrepreneur & AI-Orchestrator.
    TASK: Deep analysis of AI monetization cases.
    
    CRITICAL RULES:
    1. PRIORITIZE: Real numbers and execution details.
    2. BRAIN SYNC: In 'insight' field, suggest how to use our existing resources to clone or improve this case.
       OUR RESOURCES: {our_projects}
    3. SCRAPER PRAGMATISM: Use the provided CONTENT (often from deep scraping) to find hidden tech details.
    4. LANGUAGE: All output text MUST be in RUSSIAN.
    
    JSON FORMAT:
    [
      {{
        "source_id": 0,
        "title": "Хлёсткий заголовок",
        "profit": "Доход ИЛИ потенциал",
        "profit_num": 0,
        "category": "SaaS / LeadGen / Agency / etc",
        "tags": ["AI", "Automation"],
        "difficulty_score": 1-10,
        "scheme": "Детальный алгоритм (3-5 шагов).",
        "stack": "Список инструментов",
        "insight": "Рычаг монетизации + Синергия с нашими проектами."
      }}
    ]

    CONTEXT:
    {context}
    """

    if not GEMINI_API_KEYS: return None

    for key in GEMINI_API_KEYS:
        for model_name in ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-flash-latest"]:
            try:
                print(f"🤖 AI Analysis: {model_name}...")
                client_ai = genai.Client(api_key=key)
                res = client_ai.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                text = res.text.strip()
                if text.startswith("```json"): text = text[7:-3].strip()
                elif text.startswith("```"): text = text[3:-3].strip()
                return json.loads(text)
            except Exception as e:
                print(f"⚠️ AI Skip {model_name}: {e}")
                continue
    return None

async def run_trend_radar():
    """Анализирует последние 50 кейсов из БД для выявления трендов."""
    if not supabase: return
    try:
        print("📡 Trend Radar starting...")
        res = supabase.table("ai_money_cases").select("*").order("created_at", desc=True).limit(50).execute()
        history = "\n".join([f"- {r['title']} ({r['category']})" for r in res.data])
        
        prompt = f"Analyze these AI business cases and identify 3 hottest trends for this week. Be concise and cynical. Use Russian.\n\nCASES:\n{history}"
        
        client_ai = genai.Client(api_key=GEMINI_API_KEYS[0])
        res_ai = client_ai.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        
        trend_report = "🔥 <b>HOT TREND RADAR</b>\n\n" + res_ai.text
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        async with bot:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=trend_report, parse_mode='HTML')
    except Exception as e: print(f"❌ Trend Radar error: {e}")

async def main():
    print(f"🚀 Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Trend Radar по воскресеньям (или принудительно)
    if datetime.now().weekday() == 6: # Sunday
        await run_trend_radar()

    async with httpx.AsyncClient(follow_redirects=True) as client_http:
        tasks = [fetch_hacker_news(client_http), fetch_github(client_http), fetch_reddit(client_http), fetch_rss()]
        results = await asyncio.gather(*tasks)
    
    all_cases = [item for sublist in results for item in sublist]
    print(f"📊 New candidates: {len(all_cases)}")

    if all_cases:
        raw_list = await analyze_cases(all_cases)
        if raw_list:
            final_cases = []
            for rc in raw_list:
                idx = rc.get("source_id")
                if idx is not None and 0 <= idx < len(all_cases):
                    rc["url"] = all_cases[idx]["url"]
                    rc["source"] = all_cases[idx]["source"]
                    final_cases.append(rc)

            fresh_cases = [c for c in final_cases if not await is_duplicate(c['url'])] if final_cases else []
            if not fresh_cases:
                print("📭 No fresh unique cases.")
                return

            report, markup = build_telegram_report(fresh_cases)
            try:
                bot = Bot(token=TELEGRAM_BOT_TOKEN)
                async with bot:
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=report, parse_mode='HTML', 
                                         disable_web_page_preview=True, reply_markup=markup)
                print("✉️ Telegram sent")
            except Exception as e: print(f"❌ Telegram send error: {e}")
            
            if supabase:
                safe_columns = {'title', 'profit', 'profit_num', 'category', 'scheme', 'stack', 'url', 'source', 'difficulty_score', 'tags', 'insight'}
                for c in fresh_cases:
                    try:
                        db_case = {k: v for k, v in c.items() if k in safe_columns}
                        supabase.table("ai_money_cases").upsert({**db_case, "created_at": datetime.now(timezone.utc).isoformat()}, on_conflict="url").execute()
                        save_to_obsidian(c)
                    except Exception as e: print(f"❌ Save error: {e}")
        else: print("⚠️ Analysis failed.")
    else: print("📭 No new cases.")

if __name__ == "__main__":
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
