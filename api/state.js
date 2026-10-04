// Vercel serverless function backing the "shared team database" persistence tier.
//
// Contract (matches what index.html's client code expects):
//   GET  /api/state -> 200 { configured: boolean, authorized: boolean, state: object|null }
//   PUT  /api/state -> 200 { ok: true }  (body: the full ledger state as JSON)
//                   -> 4xx { error: string } when not configured / not authorized
//   any other method -> 405
//
// Primary Storage: Supabase PostgreSQL (lextria_state table)
//   - SUPABASE_URL: Project URL (e.g. https://xxx.supabase.co)
//   - SUPABASE_SERVICE_ROLE_KEY: Service role secret key to read/write with RLS
//
// Fallback Storage: Upstash Redis (Vercel Marketplace)
//   - KV_REST_API_URL / KV_REST_API_TOKEN
//
// Security:
//   - LEXTRIA_API_KEY: Team access key checked via 'Authorization: Bearer <key>' or 'X-Lextria-Key: <key>'

const { createClient } = require('@supabase/supabase-js');
const { Redis } = require('@upstash/redis');

const STATE_KEY = 'lextria-state';

let cachedSupabase = null;
let cachedRedis = null;

function cleanSupabaseUrl(raw) {
  if (!raw) return '';
  let url = raw.trim().replace(/^["']|["']$/g, '').trim();
  url = url.replace(/\/rest\/v1\/?$/i, '').replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(url)) {
    url = 'https://' + url;
  }
  return url;
}

function cleanSupabaseKey(raw) {
  if (!raw) return '';
  return raw.trim().replace(/^["']|["']$/g, '').trim();
}

function isSupabaseConfigured() {
  const url = cleanSupabaseUrl(process.env.SUPABASE_URL);
  const key = cleanSupabaseKey(process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY);
  return !!(url && key);
}

function getSupabaseClient() {
  if (!isSupabaseConfigured()) return null;
  if (!cachedSupabase) {
    const url = cleanSupabaseUrl(process.env.SUPABASE_URL);
    const key = cleanSupabaseKey(process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY);
    cachedSupabase = createClient(url, key, {
      auth: { persistSession: false }
    });
  }
  return cachedSupabase;
}

function isKvConfigured() {
  return !!(process.env.KV_REST_API_URL && process.env.KV_REST_API_TOKEN);
}

function getRedisClient() {
  if (!isKvConfigured()) return null;
  if (!cachedRedis) {
    cachedRedis = new Redis({
      url: process.env.KV_REST_API_URL,
      token: process.env.KV_REST_API_TOKEN
    });
  }
  return cachedRedis;
}

function extractProvidedKey(req) {
  const custom = req.headers['x-lextria-key'];
  if (custom) return Array.isArray(custom) ? custom[0] : custom;
  const auth = req.headers['authorization'];
  if (auth) {
    const authStr = Array.isArray(auth) ? auth[0] : auth;
    const match = /^Bearer\s+(.+)$/i.exec(authStr);
    if (match) return match[1];
  }
  return null;
}

function isAuthorized(req) {
  const rawRequired = process.env.LEXTRIA_API_KEY;
  if (!rawRequired) return true; // no key configured — open access
  const required = rawRequired.trim().replace(/^["']|["']$/g, '');
  if (!required) return true;
  const provided = extractProvidedKey(req);
  if (!provided) return false;
  const cleanProvided = provided.trim().replace(/^["']|["']$/g, '');
  return cleanProvided === required;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'PUT') {
    res.status(405).json({ error: 'Method not allowed. Use GET or PUT.' });
    return;
  }

  const supabase = getSupabaseClient();
  const redis = !supabase ? getRedisClient() : null;

  if (!supabase && !redis) {
    if (req.method === 'GET') {
      res.status(200).json({ configured: false, authorized: false, state: null });
    } else {
      res.status(400).json({
        error: 'Shared backend is not configured for this deployment. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Vercel settings.'
      });
    }
    return;
  }

  const authorized = isAuthorized(req);

  // GET
  if (req.method === 'GET') {
    if (!authorized) {
      res.status(200).json({ configured: true, authorized: false, state: null });
      return;
    }

    try {
      if (supabase) {
        const { data, error } = await supabase
          .from('lextria_state')
          .select('state')
          .eq('id', STATE_KEY)
          .maybeSingle();

        if (error) {
          console.error('Supabase query error:', error);
          res.status(500).json({ configured: true, authorized: true, state: null, error: 'Could not read from Supabase database: ' + (error.message || JSON.stringify(error)) });
          return;
        }

        res.status(200).json({ configured: true, authorized: true, state: (data && data.state) || null });
        return;
      }

      // Redis fallback
      const stored = await redis.get(STATE_KEY);
      res.status(200).json({ configured: true, authorized: true, state: stored || null });
    } catch (err) {
      console.error('Database read error:', err);
      res.status(500).json({ configured: true, authorized: true, state: null, error: 'Could not read from the shared database.' });
    }
    return;
  }

  // PUT
  if (!authorized) {
    res.status(401).json({ error: 'Unauthorized — this deployment requires a valid shared backend access key.' });
    return;
  }

  let body;
  try {
    body = req.body;
  } catch (e) {
    res.status(400).json({ error: 'Malformed JSON in request body.' });
    return;
  }

  if (!body || typeof body !== 'object') {
    res.status(400).json({ error: 'Request body must be a JSON object (the full ledger state).' });
    return;
  }

  try {
    if (supabase) {
      const { error } = await supabase
        .from('lextria_state')
        .upsert(
          { id: STATE_KEY, state: body, updated_at: new Date().toISOString() },
          { onConflict: 'id' }
        );

      if (error) {
        console.error('Supabase upsert error:', error);
        res.status(500).json({ error: 'Could not save to Supabase: ' + (error.message || 'unknown error') });
        return;
      }

      res.status(200).json({ ok: true });
      return;
    }

    // Redis fallback
    await redis.set(STATE_KEY, body);
    res.status(200).json({ ok: true });
  } catch (err) {
    console.error('Database write error:', err);
    res.status(500).json({ error: 'Could not save to the shared database.' });
  }
};
