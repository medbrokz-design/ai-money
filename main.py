import os
import asyncio
import feedparser
import json
import requests
import time
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Bot
from supabase import create_client, Client

load_dotenv()

# Ключи
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Настройка AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')

# Инициализация Supabase
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_hacker_news_cases():
    print("🔍 Ищу на Hacker News...")
    timestamp = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    query = "AI revenue OR AI profit OR AI SaaS OR AI MRR"
    url = f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&numericFilters=created_at_i>{timestamp}"
    found = []
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            hits = r.json().get('hits', [])
            for hit in hits:
                found.append({
                    'title': hit['title'],
                    'text': hit.get('story_text', '')[:2000],
                    'url': hit.get('url') or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    'source': 'Hacker News'
                })
    except Exception as e:
        print(f"❌ Ошибка Hacker News: {e}")
    return found

def fetch_github_trending():
    print("🔍 Ищу тренды на GitHub (AI)...")
    date_str = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%Y-%m-%d')
    url = f"https://api.github.com/search/repositories?q=topic:ai+created:>{date_str}&sort=stars&order=desc"
    found = []
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            items = r.json().get('items', [])[:5]
            for item in items:
                found.append({
                    'title': f"GitHub Trend: {item['name']}",
                    'text': item['description'] or 'No description',
                    'url': item['html_url'],
                    'source': 'GitHub'
                })
    except Exception as e:
        print(f"❌ Ошибка GitHub: {e}")
    return found

def fetch_reddit_cases():
    print("🔍 Ищу на Reddit (через JSON)...")
    subreddits = ["SideProject", "SaaS", "Entrepreneur", "AiMoneyMaking", "IndieHackers", "solopreneur"]
    search_queries = ["AI revenue", "AI MRR", "AI profit", "AI case study"]
    found_posts = []
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    limit_date = datetime.now(timezone.utc) - timedelta(days=1)

    for sub_name in subreddits:
        try:
            # Сначала пробуем простой листинг сабреддита, если это специфичный саб
            if sub_name == "AiMoneyMaking":
                 url = f"https://www.reddit.com/r/{sub_name}/new.json?limit=10"
                 r = requests.get(url, headers=headers, timeout=10)
                 if r.status_code == 200:
                    posts = r.json().get('data', {}).get('children', [])
                    for post in posts:
                        p_data = post['data']
                        created_utc = datetime.fromtimestamp(p_data['created_utc'], timezone.utc)
                        if created_utc > limit_date:
                            # Детали поста
                            post_url = f"https://www.reddit.com{p_data['permalink']}"
                            # Иногда текст уже есть в листинге
                            text = p_data.get('selftext', '')
                            # Если текста нет, можно попробовать зайти внутрь (доп. запрос), но пока ограничимся листингом для скорости
                            
                            found_posts.append({
                                'title': p_data['title'],
                                'text': text[:2000],
                                'url': post_url,
                                'source': f"Reddit (r/{sub_name})"
                            })
            
            # Поиск по ключевым словам для остальных
            else:
                for query in search_queries:
                    url = f"https://www.reddit.com/r/{sub_name}/search.json?q={query}&sort=new&restrict_sr=1&limit=5"
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        posts = r.json().get('data', {}).get('children', [])
                        for post in posts:
                            p_data = post['data']
                            created_utc = datetime.fromtimestamp(p_data['created_utc'], timezone.utc)
                            if created_utc > limit_date:
                                found_posts.append({
                                    'title': p_data['title'],
                                    'text': p_data.get('selftext', '')[:2000],
                                    'url': f"https://www.reddit.com{p_data['permalink']}",
                                    'source': f"Reddit (r/{sub_name})"
                                })
                    time.sleep(1) # Вежливость к API
        except Exception as e:
            print(f"❌ Ошибка Reddit r/{sub_name}: {e}")
            
    # Удаляем дубликаты
    unique_posts = {p['url']: p for p in found_posts}.values()
    return list(unique_posts)

def fetch_rss_cases():
    print("🔍 Ищу в RSS лентах...")
    RSS_FEEDS = ["https://medium.com/feed/tag/ai-monetization", "https://www.indiehackers.com/rss"]
    news_items = []
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                published_parsed = getattr(entry, 'published_parsed', None)
                if published_parsed:
                    pub_date = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_date > yesterday:
                        news_items.append({
                            'title': entry.title,
                            'text': entry.summary if 'summary' in entry else '',
                            'url': entry.link,
                            'source': 'RSS'
                        })
        except Exception as e:
            print(f"❌ Ошибка RSS {url}: {e}")
    return news_items

def analyze_cases(cases):
    if not cases: return None, None

    context = ""
    for i, c in enumerate(cases[:15], 1):
        context += f"--- SOURCE {i} ({c['source']}) ---\nTitle: {c['title']}\nContent: {c['text']}\nURL: {c['url']}\n\n"

    prompt = f"""
    Ты — ведущий аналитик венчурного фонда, специализирующийся на AI-стартапах и микро-SaaS. 
    Твоя задача: на основе входящих данных составить отчет о 2-3 самых перспективных и реальных кейсах заработка.

    ВЫДАЙ ОТВЕТ СТРОГО В ФОРМАТЕ JSON. 
    ФОРМАТ JSON:
    {{
      "telegram_post": "Текст общего поста для канала...",
      "cases": [
        {{
          "title": "Название кейса",
          "profit": "Профит (цифры/описание)",
          "profit_num": 1234.5,
          "category": "Категория",
          "tags": ["Tag1", "Tag2"],
          "difficulty_score": 5,
          "scheme": "Пошаговая реализация",
          "stack": "Технологический стек",
          "url": "Ссылка на источник",
          "source": "Источник"
        }}
      ]
    }}

    ПРАВИЛА ТЕЛЕГРАМ-ПОСТА (HTML):
    - Заголовок: 🔥 <b>КЕЙСЫ ЗАРАБОТКА: AI МОНЕТИЗАЦИЯ</b>
    - Вводная часть: короткий, дерзкий инсайт о текущем рынке AI (1-2 предложения).
    - Каждый кейс оформи по шаблону:
      🚀 <b>Кейс: [Название]</b>
      💰 Профит: <i>[Описание профита]</i>
      🛠 Стек: <code>[Инструменты]</code>
      📍 <a href="[url]">Читать подробнее в источнике</a>

    - В конце добавь разделитель и теги:
      _______________________
      #AI #MoneyCases #SaaS #[Category]

    - Используй ТОЛЬКО <b>, <i>, <a>, <code>.
    - Для новых строк используй \n.
    """

    response = model.generate_content(prompt)
    try:
        text = response.text.strip()
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0]
        elif '```' in text:
            text = text.split('```')[1].split('```')[0]
        
        result = json.loads(text.strip())
        post = result.get("telegram_post", "")
        post = post.replace("<br>", "\n").replace("<br/>", "\n").replace("<p>", "").replace("</p>", "\n")
        return post, result.get("cases")
    except Exception as e:
        print(f"❌ Ошибка JSON: {e}")
        return None, None

def save_to_supabase(cases):
    if not supabase or not cases: return
    for case in cases:
        try:
            supabase.table("ai_money_cases").upsert({
                "title": case['title'], "profit": case['profit'], "profit_num": case.get('profit_num', 0),
                "category": case.get('category', 'Other'), "tags": case.get('tags', []),
                "difficulty_score": case.get('difficulty_score', 5), "scheme": case['scheme'],
                "stack": case['stack'], "url": case['url'], "source": case['source'],
                "created_at": datetime.now(timezone.utc).isoformat()
            }, on_conflict="url").execute()
            print(f"💾 Сохранено: {case['title']}")
        except Exception as e:
            print(f"❌ Supabase error: {e}")

async def send_to_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not text: return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode='HTML', disable_web_page_preview=True)

async def main():
    print("🚀 ГЛОБАЛЬНЫЙ ПОИСК КЕЙСОВ...")
    hn = fetch_hacker_news_cases()
    gh = fetch_github_trending()
    rd = fetch_reddit_cases()
    rs = fetch_rss_cases()
    
    all_cases = hn + gh + rd + rs
    print(f"📊 Найдено материалов: {len(all_cases)}")
    
    if all_cases:
        report, cases_list = analyze_cases(all_cases)
        if report:
            print(report)
            await send_to_telegram(report)
            if cases_list: save_to_supabase(cases_list)
    else:
        print("❌ Ничего не найдено.")

if __name__ == "__main__":
    asyncio.run(main())