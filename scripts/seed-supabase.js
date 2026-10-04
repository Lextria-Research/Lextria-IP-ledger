// Script to seed or migrate the Lextria IP Ledger state into Supabase
//
// Usage:
//   node scripts/seed-supabase.js <SUPABASE_URL> <SUPABASE_SERVICE_ROLE_KEY>
// or set environment variables:
//   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... node scripts/seed-supabase.js

const fs = require('fs');
const path = require('path');

const supabaseUrl = process.argv[2] || process.env.SUPABASE_URL;
const serviceKey = process.argv[3] || process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseUrl || !serviceKey) {
  console.error('\n❌ Error: Missing Supabase URL or Service Role Key.\n');
  console.log('Usage:');
  console.log('  node scripts/seed-supabase.js <SUPABASE_URL> <SUPABASE_SERVICE_ROLE_KEY>\n');
  console.log('Example:');
  console.log('  node scripts/seed-supabase.js "https://xyzcompany.supabase.co" "eyJh..."\n');
  process.exit(1);
}

let backupPath = path.join(__dirname, '..', 'data', 'portfolio_backup.json');
if (!fs.existsSync(backupPath)) {
  const externalPath = path.join(process.env.USERPROFILE || 'C:\\Users\\ASUS', 'Documents', 'lextria-backups', 'portfolio_backup.json');
  if (fs.existsSync(externalPath)) {
    backupPath = externalPath;
  } else {
    console.error('❌ Could not find portfolio_backup.json in data/ or C:\\Users\\ASUS\\Documents\\lextria-backups\\');
    process.exit(1);
  }
}

const rawData = fs.readFileSync(backupPath, 'utf8');
const state = JSON.parse(rawData);

console.log(`\n📦 Loaded portfolio backup:`);
console.log(`   - Matters: ${state.records ? state.records.length : 0}`);
console.log(`   - Clients: ${state.clients ? state.clients.length : 0}`);
console.log(`   - Version: ${state.portfolioVersion || 'unknown'}`);

const cleanUrl = supabaseUrl.replace(/\/rest\/v1\/?$/i, '').replace(/\/+$/, '');
const endpoint = `${cleanUrl}/rest/v1/lextria_state`;

console.log(`\n🚀 Uploading state to Supabase (${endpoint})...`);

async function seed() {
  try {
    const payload = {
      id: 'lextria-state',
      state: state,
      updated_at: new Date().toISOString()
    };

    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'apikey': serviceKey,
        'Authorization': `Bearer ${serviceKey}`,
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=representation'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`\n❌ Failed to upload to Supabase: HTTP ${res.status} ${res.statusText}`);
      console.error(errText);
      process.exit(1);
    }

    const result = await res.json();
    console.log(`\n✅ SUCCESS! State successfully saved into Supabase table "lextria_state".`);
    console.log(`   Matters ready: ${state.records ? state.records.length : 0}`);
    console.log(`   Clients ready: ${state.clients ? state.clients.length : 0}`);
    console.log(`\nNext: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Vercel to switch live traffic.\n`);
  } catch (err) {
    console.error('\n❌ Unexpected error while communicating with Supabase:', err);
    process.exit(1);
  }
}

seed();
