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
  let url = raw.trim().replace(/^["'`]+|["'`]+$/g, '').trim();
  const match = url.match(/([a-z0-9_-]+\.supabase\.co)/i);
  if (match) {
    return 'https://' + match[1];
  }
  url = url.replace(/\/rest\/v1\/?$/i, '').replace(/\/+$/, '');
  url = url.replace(/^(https?:\/\/)+/i, '');
  return 'https://' + url;
}

function cleanSupabaseKey(raw) {
  if (!raw) return '';
  return raw.trim().replace(/^["'`]+|["'`]+$/g, '').trim();
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

async function syncIpLedgerToCore(supabase, state) {
  if (!state || !Array.isArray(state.records)) return;
  try {
    const stateClients = state.clients || [];
    if (stateClients.length > 0) {
      const { data: existingClients } = await supabase.schema('core').from('clients').select('client_name');
      const existingNames = new Set((existingClients || []).map((c) => (c.client_name || '').trim().toLowerCase()));
      const newClients = stateClients
        .filter((sc) => sc.name && !existingNames.has(sc.name.trim().toLowerCase()))
        .map((sc) => ({
          client_name: sc.name.trim(),
          client_code: sc.name.trim().slice(0, 6).toUpperCase().replace(/[^A-Z0-9]/g, '') || 'CLNT',
          entity_type: 'OTHER',
        }));
      if (newClients.length > 0) {
        await supabase.schema('core').from('clients').insert(newClients);
      }
    }

    const { data: coreClients } = await supabase.schema('core').from('clients').select('id, client_name');
    const clientMap = new Map();
    (coreClients || []).forEach((c) => clientMap.set((c.client_name || '').trim().toLowerCase(), c.id));
    const stateClientIdToCoreId = new Map();
    stateClients.forEach((sc) => {
      const cId = clientMap.get((sc.name || '').trim().toLowerCase());
      if (cId) stateClientIdToCoreId.set(sc.id, cId);
    });

    const defaultClientId = clientMap.get('independent applicants') || (coreClients && coreClients[0]?.id);

    for (const r of state.records) {
      let rawCode = (r.code || '').trim();
      if (!rawCode) continue;
      if (rawCode.toUpperCase() === 'LT09') rawCode = 'TM-LT09';

      const clientId = stateClientIdToCoreId.get(r.clientId) || defaultClientId;
      if (!clientId) continue;

      let status = 'ACTIVE';
      const s = (r.status || '').toLowerCase();
      if (s.includes('registered') || s.includes('granted')) status = 'COMPLETED';
      else if (s.includes('abandon') || s.includes('refused') || s.includes('withdraw')) status = 'ABANDONED';

      const title = r.brand || (r.desc ? r.desc.slice(0, 80) : '') || ((r.ipType || 'IP').toUpperCase() + ' ' + rawCode);

      const { data: existing } = await supabase
        .schema('core')
        .from('project_codes')
        .select('id, status')
        .eq('code', rawCode)
        .maybeSingle();

      if (!existing) {
        await supabase.schema('core').from('project_codes').insert({
          code: rawCode,
          department: 'IP_SOFT',
          client_id: clientId,
          title: title,
          status: status,
          owning_app: 'IP_LEDGER',
        });
      } else if (existing.status !== status) {
        await supabase.schema('core').from('project_codes').update({ status, title }).eq('id', existing.id);
      }
    }
  } catch (err) {
    console.warn('Background syncIpLedgerToCore warning:', err?.message || err);
  }
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
          const cause = error.cause ? (error.cause.message || error.cause.code || String(error.cause)) : null;
          const currentUrl = cleanSupabaseUrl(process.env.SUPABASE_URL);
          let targetHost = null;
          try { targetHost = new URL(currentUrl).host; } catch (e) { targetHost = 'invalid-url: ' + currentUrl; }
          res.status(500).json({
            configured: true,
            authorized: true,
            state: null,
            error: 'Could not read from Supabase database: ' + (error.message || JSON.stringify(error)) + (cause ? ' (Cause: ' + cause + ')' : ''),
            targetHost: targetHost
          });
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

      // Ecosystem Interlinking: Asynchronously sync clients and matters to core.clients and core.project_codes
      syncIpLedgerToCore(supabase, body).catch((e) => console.warn('syncIpLedgerToCore error:', e));

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
