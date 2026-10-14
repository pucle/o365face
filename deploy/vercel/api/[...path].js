// Vercel Edge Function: chuyển tiếp mọi /api/* tới backend (Hugging Face Space) cùng origin với UI -> không cần CORS.
// Nếu Space ở chế độ Private, đặt HF_TOKEN trong biến môi trường của Vercel: token được gắn ở đây, không lộ ra trình duyệt.
export const config = { runtime: 'edge' };

export default async function handler(request) {
  const base = (process.env.BACKEND_URL || '').replace(/\/+$/, '');
  if (!base) {
    return new Response(JSON.stringify({ detail: 'Thiếu biến môi trường BACKEND_URL trên Vercel (vd https://user-space.hf.space).' }),
      { status: 500, headers: { 'content-type': 'application/json' } });
  }
  const u = new URL(request.url);
  const headers = new Headers(request.headers);
  ['host', 'connection', 'x-forwarded-host', 'x-forwarded-proto', 'x-forwarded-for', 'x-vercel-id'].forEach((h) => headers.delete(h));
  if (process.env.HF_TOKEN) headers.set('Authorization', 'Bearer ' + process.env.HF_TOKEN);
  const init = { method: request.method, headers, redirect: 'manual' };
  if (request.method !== 'GET' && request.method !== 'HEAD') { init.body = request.body; init.duplex = 'half'; }
  try {
    const r = await fetch(base + u.pathname + u.search, init);
    const out = new Headers(r.headers);
    out.delete('content-encoding'); out.delete('content-length');
    return new Response(r.body, { status: r.status, headers: out });
  } catch (e) {
    return new Response(JSON.stringify({ detail: 'Không gọi được backend: ' + e }), { status: 502, headers: { 'content-type': 'application/json' } });
  }
}
