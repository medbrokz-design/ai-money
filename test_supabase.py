import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

try:
    # Try to fetch one row to see columns
    res = supabase.table("ai_money_cases").select("*").limit(1).execute()
    print("Table exists. Columns received:", res.data)
except Exception as e:
    print("Error accessing table:", e)
