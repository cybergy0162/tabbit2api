#!/usr/bin/env node
/**
 * refresh_fnos_token.mjs — 一键刷新 Tabbit2API 的 Token（2 步法第 2 步）
 *
 * 做四件事：
 *   1) 从本机已登录的 Tabbit 桌面端导出 Access Token
 *   2) 登录你的 Tabbit2API 面板 admin，把 token 写入（同名则更新，否则新增）
 *   3) 触发 test-models 刷新模型目录
 *   4) 跑一次真实对话验证
 *
 * 用法：
 *   node refresh_fnos_token.mjs
 *
 * 首次运行会提示输入「面板地址」和「admin 密码」，并记住到 ~/.tabbit2api-fnos.json，
 * 以后直接跑即可（无需再输）。也可用下列方式预先配置：
 *   命令行：  --url http://<你的NAS>:8800  --password ***  --name tabbit-ai  --base https://web.tabbit.ai
 *   配置文件：  ~/.tabbit2api-fnos.json  形如 {"url":"...","password":"***","name":"tabbit-ai","base":"https://web.tabbit.ai"}
 *   环境变量：  FNOS_URL / ADMIN_PW / TOKEN_NAME / BASE_URL
 * 优先级：命令行 > 配置文件 > 环境变量 > （缺失则交互输入 / 内置默认）
 *
 * 改过 admin 密码后：删除或编辑 ~/.tabbit2api-fnos.json，或加 --password ***
 */
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { createInterface } from 'node:readline/promises';

const HERE = dirname(fileURLToPath(import.meta.url));
const log = (...a) => console.log(...a);

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : undefined;
}

// ── 本地配置（可选）──
const CONF_PATH = join(homedir(), '.tabbit2api-fnos.json');
let conf = {};
if (existsSync(CONF_PATH)) {
  try { conf = JSON.parse(readFileSync(CONF_PATH, 'utf8')) || {}; } catch { /* ignore */ }
}

// ── 规范化面板地址：补 scheme、补默认端口 8800 ──
function normalizeUrl(u) {
  u = String(u || '').trim().replace(/\/+$/, '');
  if (!u) return '';
  if (!/^https?:\/\//i.test(u)) u = 'http://' + u;
  try {
    const url = new URL(u);
    if (!url.port) url.port = '8800';
    const path = url.pathname && url.pathname !== '/' ? url.pathname.replace(/\/+$/, '') : '';
    return url.origin + path;
  } catch { return u; }
}

let FNOS = arg('url') || conf.url || process.env.FNOS_URL || '';
let PW = arg('password') || conf.password || process.env.ADMIN_PW || '';
let NAME = arg('name') || conf.name || process.env.TOKEN_NAME || 'tabbit-ai';
let BASE_URL = arg('base') || conf.base || process.env.BASE_URL || 'https://web.tabbit.ai';

FNOS = normalizeUrl(FNOS);

// ── 缺失则交互输入（非 TTY 环境直接报错，避免卡住）──
if (!FNOS || !PW) {
  const interactive = process.stdin.isTTY;
  if (!interactive) {
    console.error('缺少面板地址或 admin 密码，且当前非交互环境。请用参数/配置文件/环境变量提供：');
    console.error('  node refresh_fnos_token.mjs --url http://<你的NAS>:8800 --password ***');
    process.exit(1);
  }
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  if (!FNOS) {
    const a = (await rl.question('请输入 Tabbit2API 面板地址（如 http://192.168.1.10:8800）: ')).trim();
    FNOS = normalizeUrl(a);
    if (!FNOS) { console.error('未提供面板地址，退出。'); rl.close(); process.exit(1); }
  }
  if (!PW) {
    const a = (await rl.question('请输入面板 admin 密码（默认 admin，直接回车用默认）: ')).trim();
    PW = a || 'admin';
  }
  rl.close();
  // 记住配置，下次免输入
  try {
    writeFileSync(CONF_PATH, JSON.stringify({ url: FNOS, password: PW, name: NAME, base: BASE_URL }, null, 2));
    log(`（已记住配置到 ${CONF_PATH}，下次直接运行即可）\n`);
  } catch (e) { log(`（配置写入失败，忽略：${e.message}）`); }
}

log(`面板地址: ${FNOS}`);

// ── 1. 导出 token ──
log(`[1/4] 从本机 Tabbit 导出 token ...`);
let raw;
try {
  raw = execFileSync(process.execPath, [join(HERE, 'get_tabbit_token.mjs')], {
    cwd: HERE, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
  });
} catch (e) {
  console.error('导出失败：', e.stderr || e.message);
  console.error('请确认：1) Tabbit 桌面端已登录 web.tabbit.ai；2) 已完全退出 Tabbit（避免 profile 占用）。');
  process.exit(1);
}
const cand = raw.split('\n').map(s => s.trim())
  .filter(s => s.startsWith('eyJ') && s.split('|').length >= 2);
const token = cand[cand.length - 1];
if (!token) { console.error('未能从脚本输出解析出 token。原始输出：\n' + raw.slice(-800)); process.exit(2); }
log(`      得到 token，长度 ${token.length}，前缀 ${token.slice(0, 16)}...`);

// ── HTTP helper ──
async function api(path, opts = {}, jwt) {
  const headers = { 'Content-Type': 'application/json' };
  if (jwt) headers['Authorization'] = 'Bearer ' + jwt;
  const r = await fetch(FNOS + path, { ...opts, headers });
  const t = await r.text();
  try { return { status: r.status, body: JSON.parse(t) }; }
  catch { return { status: r.status, body: t }; }
}

// ── 2. 登录面板 ──
log(`[2/4] 登录面板 ...`);
const li = await api('/api/admin/login', { method: 'POST', body: JSON.stringify({ password: PW }) });
if (li.status !== 200 || !li.body.token) {
  console.error('登录失败：', JSON.stringify(li.body));
  console.error('若已改过 admin 密码：编辑 ~/.tabbit2api-fnos.json 的 password 字段，或用 --password ***');
  process.exit(3);
}
const jwt = li.body.token;
log('      登录成功');

// ── 3. 写入 token ──
log(`[3/4] 写入 token（名称 "${NAME}"）...`);
const list = await api('/api/admin/tokens', {}, jwt);
const exist = (list.body.tokens || []).find(t => t.name === NAME);
if (exist) {
  const up = await api(`/api/admin/tokens/${exist.id}`, {
    method: 'PUT', body: JSON.stringify({ value: token, enabled: true }),
  }, jwt);
  log(up.status === 200 ? `      已更新现有 token (${exist.id})` : `      更新失败：${JSON.stringify(up.body)}`);
} else {
  const add = await api('/api/admin/tokens', {
    method: 'POST', body: JSON.stringify({ name: NAME, value: token, enabled: true }),
  }, jwt);
  log(add.status === 200 ? `      已新增 token (${add.body.id})` : `      新增失败：${JSON.stringify(add.body)}`);
}
await api('/api/admin/settings', { method: 'PUT', body: JSON.stringify({ base_url: BASE_URL }) }, jwt);
log(`      base_url 设为 ${BASE_URL}`);

// ── 4. 刷新模型 + 验证 ──
log(`[4/4] 刷新模型目录 ...`);
const tm = await api('/api/admin/test-models', { method: 'POST' }, jwt);
log('      ' + (tm.body.message || JSON.stringify(tm.body)));

const chat = await api('/v1/chat/completions', {
  method: 'POST',
  body: JSON.stringify({ model: 'best', messages: [{ role: 'user', content: '只回复两个字：你好' }], stream: false }),
});
const content = chat.body?.choices?.[0]?.message?.content;
log(content ? `\n✅ 验证通过，模型返回：${content}` : `\n⚠️ 验证异常：${JSON.stringify(chat.body).slice(0, 200)}`);
if (content) {
  const exp = (() => { try { const p = token.split('|')[0].split('.')[1]; const s = p + '='.repeat((4 - p.length % 4) % 4); return JSON.parse(Buffer.from(s, 'base64url')).exp; } catch { return 0; } })();
  if (exp) log(`   Token 有效期至 ${new Date(exp * 1000).toISOString().replace('T', ' ').slice(0, 19)} UTC（约 ${((exp - Date.now() / 1000) / 86400).toFixed(1)} 天）`);
}
