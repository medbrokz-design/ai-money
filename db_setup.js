const { Client } = require('pg');

const client = new Client({
  user: 'postgres.tsqfesxtqrwpnqruzajs',
  host: 'aws-0-eu-west-1.pooler.supabase.com',
  database: 'postgres',
  password: 'sb_secret__VKorD5x3VfcakLzNqXiKQ_v_8KeGNs',
  port: 6543,
  ssl: {
    rejectUnauthorized: false
  }
});

async function run() {
  try {
    await client.connect();
    console.log("Connected to Supabase via Pooler!");
    
    const sql = `
      create table if not exists ai_money_cases (
        id bigint generated always as identity primary key,
        created_at timestamptz default now(),
        title text,
        profit text,
        profit_num numeric,
        category text,
        tags text[],
        scheme text,
        stack text,
        url text unique,
        source text,
        difficulty_score int check (difficulty_score >= 1 and difficulty_score <= 10)
      );
    `;
    
    await client.query(sql);
    console.log("Table ai_money_cases created/updated successfully!");
    
    const alterSql = `
      alter table ai_money_cases add column if not exists profit_num numeric;
      alter table ai_money_cases add column if not exists category text;
      alter table ai_money_cases add column if not exists tags text[];
      alter table ai_money_cases add column if not exists difficulty_score int;
    `;
    await client.query(alterSql);
    console.log("Columns verified!");

  } catch (err) {
    console.error("Connection error:", err.message);
    if (err.message.includes("ENOTFOUND")) {
        console.log("Host not found. Trying us-east-1...");
        // Re-run with us-east-1 could be here but let's try manually if it fails
    }
  } finally {
    await client.end();
  }
}

run();