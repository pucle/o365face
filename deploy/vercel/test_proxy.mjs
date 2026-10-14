// Thử hàm proxy cục bộ (không cần Vercel CLI):  BACKEND_URL=http://127.0.0.1:7860 API_TOKEN=dev node deploy/vercel/test_proxy.mjs
import handler from './api/[...path].js';
import assert from 'node:assert';
process.env.BACKEND_URL ||= 'http://127.0.0.1:7860';
const T = process.env.API_TOKEN || 'dev';
const call = (path, init) => handler(new Request('https://ui.example' + path, init));
let r = await call('/api/health'); assert.equal(r.status, 200); console.log('ok  health', await r.json());
r = await call('/api/members'); assert.equal(r.status, 401); console.log('ok  thiếu token bị từ chối:', (await r.json()).detail);
r = await call('/api/members', { method: 'POST', headers: { 'X-API-Token': T, 'content-type': 'application/json' }, body: JSON.stringify({ member_id: 'proxytest', name: 'Proxy Test' }) });
assert.equal(r.status, 200); console.log('ok  POST JSON qua proxy');
const fd = new FormData(); fd.append('file', new Blob([Uint8Array.from(atob('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA='), c => c.charCodeAt(0))], { type: 'image/jpeg' }), 'x.jpg');
r = await call('/api/pose', { method: 'POST', headers: { 'X-API-Token': T }, body: fd });
console.log('    multipart /api/pose ->', r.status, r.status === 200 ? JSON.stringify(await r.json()) : await r.text());
assert.ok([200, 400].includes(r.status));
r = await call('/api/members/proxytest', { method: 'DELETE', headers: { 'X-API-Token': T } }); assert.equal(r.status, 200); console.log('ok  DELETE');
delete process.env.BACKEND_URL; r = await call('/api/health'); assert.equal(r.status, 500); console.log('ok  thiếu BACKEND_URL báo lỗi rõ');
console.log('PROXY OK');
