#!/usr/bin/env node
/**
 * get_tabbit_token.mjs — 从本机已登录的 Tabbit 浏览器中导出 Tabbit2API 所需的 Access Token
 *
 * 跨平台：macOS / Windows / Linux。
 * 原理：Tabbit 基于 Chromium，登录后会在 `web.tabbit.ai`（或 `web.tabbit.com`）域下
 *       写入 `token` Cookie（一个 JWT）。本脚本用 Playwright 以「复制的已登录 profile」
 *       启动 Tabbit 内核，直接读取 Cookie，拼成 Tabbit2API 需要的
 *       `token|next-auth.session-token|device_id` 形式（缺失段可省略）。
 *
 * 依赖：node >= 18，playwright-core（或 playwright）
 *   npm i -D playwright-core
 *
 * 用法（先完全退出 Tabbit 应用）：
 *   node tools/get_tabbit_token.mjs
 *   node tools/get_tabbit_token.mjs --site "https://web.tabbit.com"    # 国内版
 *   node tools/get_tabbit_token.mjs --profile "/path/to/profile"        # 自定义 profile
 *   node tools/get_tabbit_token.mjs --app "/path/to/Tabbit(.exe)"       # 自定义内核
 *
 * 注意：
 *   - 脚本会先把 profile 复制到临时目录再读取，避免占用/锁住正在运行的 Tabbit。
 *   - 输出的 token 是敏感凭证，请勿泄露；有效期约 7 天，过期后重新运行即可。
 *   - Windows 的 Cookie 采用「应用绑定加密（app-bound encryption）」，
 *     必须用 **Tabbit 自带的 Tabbit.exe** 启动才能解密 —— 本脚本已自动探测其安装位置。
 */
import { chromium } from 'playwright-core';
import { cpSync, rmSync, mkdtempSync, existsSync, readdirSync, statSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const H = homedir();
const isWin = process.platform === 'win32';
const isMac = process.platform === 'darwin';

// ── 探测 profile 目录（含 Default 子目录的那个）──
function profileCandidates() {
  if (isMac) return [join(H, 'Library/Application Support/Tabbit')];
  if (isWin) {
    const local = process.env.LOCALAPPDATA || '';
    const roaming = process.env.APPDATA || '';
    return [
      join(local, 'Tabbit', 'User Data'),
      join(local, 'Tabbit'),
      join(roaming, 'Tabbit', 'User Data'),
      join(roaming, 'Tabbit'),
    ];
  }
  return [join(H, '.config/Tabbit'), join(H, '.config/tabbit')];
}

function detectProfile() {
  const cands = profileCandidates();
  // 优先：存在且含 Default 子目录
  for (const c of cands) if (c && existsSync(join(c, 'Default'))) return c;
  // 次选：直接存在
  for (const c of cands) if (c && existsSync(c)) return c;
  return cands[0] || '';
}

// ── 探测 Tabbit 可执行文件 ──
function findExeUnder(dir, exeName) {
  try {
    for (const e of readdirSync(dir)) {
      const p = join(dir, e);
      let st; try { st = statSync(p); } catch { continue; }
      if (!st.isDirectory()) continue;
      const direct = join(p, exeName);
      if (existsSync(direct)) return direct;
      const electron = join(p, 'Application', exeName); // Electron 布局
      if (existsSync(electron)) return electron;
      try {
        for (const e2 of readdirSync(p)) {
          const c2 = join(p, e2, exeName);
          if (existsSync(c2)) return c2;
        }
      } catch {}
    }
  } catch {}
  return null;
}

function detectApp() {
  if (isMac) {
    const p = '/Applications/Tabbit.app/Contents/MacOS/Tabbit';
    return existsSync(p) ? p : undefined;
  }
  if (isWin) {
    const local = process.env.LOCALAPPDATA || '';
    const pf = process.env.ProgramFiles || 'C:\\Program Files';
    const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
    // 常见安装位置直查
    const direct = [
      join(local, 'Programs', 'Tabbit', 'Tabbit.exe'),
      join(local, 'Programs', 'tabbit', 'Tabbit.exe'),
      join(local, 'Programs', 'Tabbit Browser', 'Tabbit.exe'),
      join(pf, 'Tabbit', 'Tabbit.exe'),
      join(pf86, 'Tabbit', 'Tabbit.exe'),
      join(pf, 'Tabbit Browser', 'Tabbit.exe'),
    ];
    for (const c of direct) if (existsSync(c)) return c;
    // 扫目录兜底
    for (const root of [join(local, 'Programs'), pf, pf86]) {
      const hit = findExeUnder(root, 'Tabbit.exe');
      if (hit) return hit;
    }
    return undefined;
  }
  return undefined;
}

const profileSrc = arg('profile', detectProfile());
const appPath = arg('app', detectApp());
const site = arg('site', 'https://web.tabbit.ai');

if (!profileSrc || !existsSync(profileSrc)) {
  console.error(`找不到 profile 目录: ${profileSrc || '<未探测到>'}`);
  console.error('候选位置:\n  ' + profileCandidates().filter(Boolean).join('\n  '));
  console.error('请用 --profile 指定。');
  process.exit(1);
}

if (!appPath) {
  console.error('未探测到 Tabbit 可执行文件。');
  if (isWin) {
    console.error('请用 --app 指定，例如：');
    console.error('  --app "%LOCALAPPDATA%\\Programs\\Tabbit\\Tabbit.exe"');
    console.error('（Windows 必须用 Tabbit 自带的 Tabbit.exe，否则无法解密 app-bound 加密的 Cookie）');
  } else {
    console.error('请用 --app 指定 Tabbit 内核路径。');
  }
  process.exit(1);
}

console.log(`平台: ${process.platform}`);
console.log(`内核: ${appPath}`);
console.log(`profile: ${profileSrc}`);

const work = mkdtempSync(join(tmpdir(), 'tabbit-tok-'));
const profileCopy = join(work, 'profile');
console.log(`复制 profile -> ${profileCopy}`);
cpSync(profileSrc, profileCopy, { recursive: true });
// 清理锁文件（各平台命名略有差异）
for (const lock of ['SingletonLock', 'SingletonCookie', 'SingletonSocket', 'lockfile', 'DevToolsActivePort']) {
  try { rmSync(join(profileCopy, lock), { force: true }); } catch {}
}

const ctx = await chromium.launchPersistentContext(profileCopy, {
  executablePath: appPath,
  headless: true,
  // 关键（macOS）：默认参数里的 --use-mock-keychain 会让 Chromium 用假钥匙串，
  // 读不出用真实 "<App> Safe Storage" 加密的 Cookie（整库被丢弃）。必须移除。
  // Windows/Linux 上该参数本就不存在，移除是无害的 no-op。
  ignoreDefaultArgs: ['--use-mock-keychain'],
  args: ['--no-first-run', '--no-default-browser-check'],
});

const cookies = {};
for (const c of await ctx.cookies(site)) cookies[c.name] = c.value;
await ctx.close();
rmSync(work, { recursive: true, force: true });

const jwt = cookies['token'] || '';
const nextAuth = cookies['next-auth.session-token'] || '';
if (!jwt) {
  console.error(`未找到 ${site} 的 \`token\` Cookie —— 请确认已在 Tabbit 中登录该站点。`);
  console.error('提示：国际版用 web.tabbit.ai，国内版用 web.tabbit.com，用 --site 指定。');
  process.exit(2);
}

const value = [jwt, nextAuth].filter(Boolean).join('|');
console.log('\n=== Tabbit2API Token（粘贴到管理面板 Tokens 页）===');
console.log(value);
console.log('\n说明：user_id 无需填写，程序会从 JWT 自动解析。');
