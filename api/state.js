// Vercel serverless function backing the "shared team database" persistence tier.
//
// Contract (matches what index.html's client code expects):
//   GET  /api/state -> 200 { configured: boolean, authorized: boolean, state: object|null }
//   PUT  /api/state -> 200 { ok: true }  (body: the full ledger state as JSON)
//                   -> 4xx { error: string } when not configured / not authorized
//   any other method -> 405
//
// Storage: Vercel retired its native "KV" product (Storage tab) in December 2024
// and migrated existing stores to Upstash Redis, reachable through the Vercel
// Marketplace. This function therefore talks to Redis via `@upstash/redis`
// rather than the now-deprecated `@vercel/kv` package — see README.md for the
// exact "add a Redis integration" steps in today's Vercel dashboard. The
// integration still injects KV_REST_API_URL / KV_REST_API_TOKEN (the same
// names the old KV product used), which is what this file reads.
//
// "configured" means those env vars are present. If they aren't, this always
// returns configured:false rather than erroring — a plain deploy with no Redis
// integration added yet is the normal zero-config case, and the client falls
// back to localStorage.
//
// "authorized" is a lightweight bearer-token check against process.env.LEXTRIA_API_KEY,
// read from either an `Authorization: Bearer <key>` header or a custom `X-Lextria-Key`
// header (whichever the caller sends). If LEXTRIA_API_KEY is not set, every request is
// treated as authorized — see the README for why that's insecure for real client data
// and should be set before this is used for anything sensitive.

const { Redis } = require('@upstash/redis');

const STATE_KEY = 'lextria-state';

let cachedClient = null;

function isKvConfigured() {
  return !!(process.env.KV_REST_API_URL && process.env.KV_REST_API_TOKEN);
}

function getClient() {
  if (!isKvConfigured()) return null;
  if (!cachedClient) {
    cachedClient = new Redis({
      url: process.env.KV_REST_API_URL,
      token: process.env.KV_REST_API_TOKEN
    });
  }
  return cachedClient;
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
  const required = process.env.LEXTRIA_API_KEY;
  if (!required) return true; // no key configured — open access (see README security note)
  const provided = extractProvidedKey(req);
  return !!provided && provided === required;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'PUT') {
    res.status(405).json({ error: 'Method not allowed. Use GET or PUT.' });
    return;
  }

  const redis = getClient();

  if (!redis) {
    if (req.method === 'GET') {
      res.status(200).json({ configured: false, authorized: false, state: null });
    } else {
      res.status(400).json({ error: 'Shared backend is not configured for this deployment. Add a Redis integration from the Vercel Marketplace.' });
    }
    return;
  }

  const authorized = isAuthorized(req);

  if (req.method === 'GET') {
    if (!authorized) {
      res.status(200).json({ configured: true, authorized: false, state: null });
      return;
    }
    try {
      const stored = await redis.get(STATE_KEY);
      res.status(200).json({ configured: true, authorized: true, state: stored || null });
    } catch (err) {
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
    body = req.body; // Vercel parses this from JSON automatically via the Content-Type header;
                      // accessing it can throw on malformed JSON, hence the try/catch.
  } catch (e) {
    res.status(400).json({ error: 'Malformed JSON in request body.' });
    return;
  }
  if (!body || typeof body !== 'object') {
    res.status(400).json({ error: 'Request body must be a JSON object (the full ledger state).' });
    return;
  }
  try {
    await redis.set(STATE_KEY, body);
    res.status(200).json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: 'Could not save to the shared database.' });
  }
};
