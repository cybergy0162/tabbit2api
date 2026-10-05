#!/usr/bin/env node
/**
 * login_and_get_token.mjs — 打开一个可见的 Tabbit 窗口完成登录，并自动导出 Tabbit2API Access Token
 *
 * 做法：把本机 Tabbit profile 复制到临时目录 → 用 Tabbit 内核以【可见窗口】启动该副本 →
 *       打开 web.tabbit.ai 登录页 → 你在窗口里完成 Google 登录 → 脚本轮询等待 `token` Cookie
 *       出现 → 打印 `token|next-auth.session-token|device_id` 形式的凭证。
 *
 * 不触碰正在运行的 Tabbit 主 profile（用副本，避免 SingletonLock 冲突）。
 *
 * 依赖：node >= 18，playwright-core
 * 用法：node tools/login_and_get_token.mjs
 *      node tools/login_and_get_token.mjs --site https://web.tabbit.com
 *      node tools/login_and_get_token.mjs --timeout 600
 */
import { chromium } from 'playwright-core';
import { cpSync, rmSync, mkdtempSync, existsSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const HOME = homedir();
const DEFAULT_PROFILE = join(HOME, 'Library/Application Support/Tabbit');
const DEFAULT_APP = '/Applications/Tabbit.app/Contents/MacOS/Tabbit';

const profileSrc = arg('profile', DEFAULT_PROFILE);
const appPath = arg('app', DEFAULT_APP);
const site = arg('site', 'https://web.tabbit.ai');
const timeoutSec = parseInt(arg('timeout', '600'), 10);

if (!existsSync(profileSrc)) { console.error('找不到 profile: ' + profileSrc); process.exit(1); }

const work = mkdtempSync(join(tmpdir(), 'tabbit-login-'));
const profileCopy = join(work, 'profile');
console.log(`复制 profile: ${profileSrc} -> ${profileCopy}`);
cpSync(profileSrc, profileCopy, { recursive: true });
for (const lock of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
  try { rmSync(join(profileCopy, lock), { force: true }); } catch {}
}

const ctx = await chromium.launchPersistentContext(profileCopy, {
  executablePath: appPath,
  headless: false,
  args: ['--no-first-run', '--no-default-browser-check'],
});

const page = ctx.pages()[0] || await ctx.newPage();
await page.goto(site + '/login', { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
console.log('\n========================================');
console.log(' 请在弹出的 Tabbit 窗口中完成 Google 登录');
console.log(' 登录成功后脚本会自动抓取 Token（最多等 ' + timeoutSec + 's）');
console.log('========================================\n');

const deadline = Date.now() + timeoutSec * 1000;
let jwt = '', nextAuth = '';
while (Date.now() < deadline) {
  const cks = await ctx.cookies(site).catch(() => []);
  const t = cks.find(c => c.name === 'token');
  if (t && t.value) { jwt = t.value; nextAuth = (cks.find(c => c.name === 'next-auth.session-token') || {}).value || ''; break; }
  await page.waitForTimeout(2000);
}

if (!jwt) {
  console.error('超时：仍未检测到 token Cookie。请确认已在窗口里登录成功。');
  await ctx.close().catch(()=>{});
  rmSync(work, { recursive: true, force: true });
  process.exit(2);
}

const value = [jwt, nextAuth].filter(Boolean).join('|');
console.log('\n=== Tabbit2API Token（粘贴到管理面板 Tokens 页）===');
console.log(value);
console.log('\n（token 长度 ' + jwt.length + '，有效期约 7 天）');

await ctx.close().catch(()=>{});
rmSync(work, { recursive: true, force: true });
process.exit(0);
