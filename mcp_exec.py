import subprocess
import json
import os
import sys

def run_mcp_query(query):
    env = os.environ.copy()
    env['SUPABASE_ACCESS_TOKEN'] = 'sb_secret__VKorD5x3VfcakLzNqXiKQ_v_8KeGNs'
    
    p = subprocess.Popen(
        'npx -y @supabase/mcp-server-supabase@latest --project-ref tsqfesxtqrwpnqruzajs --access-token sb_secret__VKorD5x3VfcakLzNqXiKQ_v_8KeGNs',
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=True,
        env=env
    )

    def send(req):
        p.stdin.write(json.dumps(req) + '\n')
        p.stdin.flush()

    # Initialize
    send({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'initialize',
        'params': {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1.0'}
        }
    })
    p.stdout.readline()
    
    send({'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {}})
    
    # Run SQL
    send({
        'jsonrpc': '2.0',
        'id': 3,
        'method': 'tools/call',
        'params': {
            'name': 'execute_sql',
            'arguments': {'query': query}
        }
    })
    
    response = p.stdout.readline()
    print(response)
    p.terminate()

sql = """
alter table ai_money_cases 
add column if not exists profit_num numeric,
add column if not exists category text,
add column if not exists tags text[],
add column if not exists difficulty_score int check (difficulty_score >= 1 and difficulty_score <= 10);
"""

run_mcp_query(sql)
