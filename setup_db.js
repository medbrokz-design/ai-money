const { createClient } = require('@supabase/supabase-js');

const supabaseUrl = 'https://tsqfesxtqrwpnqruzajs.supabase.co';
const supabaseKey = 'sb_secret__VKorD5x3VfcakLzNqXiKQ_v_8KeGNs';
const supabase = createClient(supabaseUrl, supabaseKey);

async function createTable() {
  const sql = `
    create table if not exists ai_money_cases (
      id bigint generated always as identity primary key,
      created_at timestamptz default now(),
      title text,
      profit text,
      scheme text,
      stack text,
      url text unique,
      source text
    );
  `;
  
  // Supabase JS doesn't have an executeSql method for the client directly in the public API
  // but we can try to use a RPC or just assume the user will create it if we can't.
  // However, we can try to use the management API if we had the PAT.
  
  console.log("Please create the table manually in the Supabase SQL Editor if it doesn't exist:");
  console.log(sql);
}

createTable();
