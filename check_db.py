import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

async def check_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Supabase credentials not found in .env")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    try:
        res = supabase.table("ai_money_cases").select("*", count="exact").order("created_at", desc=True).limit(1).execute()
        print(f"✅ Connection successful!")
        print(f"📊 Total rows in 'ai_money_cases': {res.count}")
        if res.data:
            print(f"📋 Columns: {list(res.data[0].keys())}")
        print("📝 Latest entries:")
        for row in res.data:
            print(f"- {row.get('title')} ({row.get('url')})")
    except Exception as e:
        print(f"❌ Supabase error: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(check_supabase())
