# 如何获取 Tabbit Access Token

Tabbit2API 通过 **Token 池** 调用 Tabbit 网页端，需要在管理面板里为每个 Tabbit 账号添加一个 **Access Token**。
本文说明这个 Token 是什么、怎么取、放哪里。

> 支持站点：国际版 `web.tabbit.ai` / 国内版 `web.tabbit.com`（两个均为官方站点，主要差别是内置模型与数据区域）。
> **Token 与所登录的 Tabbit 站点绑定**，请确保在**同一站点**下登录并导出，并在管理面板把 Token 加到对应**站点**。

---

## 一、Token 是什么

Tabbit 基于 Chromium。登录网页端后，`web.tabbit.ai` / `web.tabbit.com` 域下会写入名为 **`token`** 的 Cookie，其值为一个 **JWT**（`eyJ...` 三段式）。

Tabbit2API 接受的值格式为竖线分隔的三段（**只有第一段必需**）：

```
<jwt_token> | <next-auth.session-token?> | <device_id?>
```

| 段 | 来源 | 是否必需 |
|----|------|----------|
| `jwt_token` | Cookie `token` 的值 | ✅ 必需 |
| `next-auth.session-token` | Cookie `next-auth.session-token` | 可选 |
| `device_id` | 任意 UUID | 可选（缺省自动生成） |

- **`user_id` 无需填写**：程序会从 JWT 的 payload 里自动解析（`id` / `sub`）。
- 也就是说：**最少只需把 Cookie `token` 的 JWT 粘进去**即可。
- **站点无需写进 Token 值**：JWT 本身分不出站点（两站签发信息相同），站点靠你在面板添加 Token 时**选择的站点**来确定。

---

## 二、获取方式

### 方式 A：直接从浏览器复制（仅当该站点能在标准浏览器登录时）

1. 用 Tabbit 打开并登录对应站点（如 `https://web.tabbit.ai`）。
2. 打开开发者工具（F12 / ⌥⌘I）→ **Application / 应用** → **Cookies** → 选择该站点域名。
3. 找到名为 `token` 的条目，复制它的 **Value**（`eyJ...` 开头的 JWT）。
4. 打开 Tabbit2API 管理面板 → **Tokens 管理** → **添加 Token**：
   - **名称**：便于识别的账号名（如 `my-main-account`）
   - **站点**：选对（国际版 / 国内版）
   - **值**：粘贴上面复制的 JWT（如需，用 `|` 追加 `next-auth.session-token`）

> ⚠️ 实测限制：`token` 是 **HttpOnly**，`document.cookie` / Console 里看不到，必须用 Application 面板；部分站点在标准浏览器不触发登录，此时请用**方式 B**。

### 方式 B：脚本自动导出（跨平台，推荐）

仓库提供 `tools/get_tabbit_token.mjs`，用 Playwright 以「复制的已登录 profile」启动 Tabbit 内核并读出 Cookie。

```bash
# 依赖
npm i -D playwright-core

# 先完全退出 Tabbit 应用，然后：
node tools/get_tabbit_token.mjs
# 可选参数：
#   --profile "<profile 路径>"     自定义 profile 路径
#   --app "<内核可执行文件>"        自定义内核可执行文件
#   --site "https://web.tabbit.ai" 指定读取哪个站点（国内版用 https://web.tabbit.com）
```

输出即为可直接粘贴的 Token 值。
脚本会自动把 profile 复制到临时目录再读取，不会占用/锁住正在运行的 Tabbit。

#### 跨平台说明

| 平台 | profile 默认位置 | 内核可执行文件 |
|------|------------------|----------------|
| macOS | `~/Library/Application Support/Tabbit` | 自动探测 `/Applications/Tabbit.app/Contents/MacOS/Tabbit` |
| Windows | `%LOCALAPPDATA%\Tabbit\User Data` 等 | 自动探测 `%LOCALAPPDATA%\Programs\Tabbit\Tabbit.exe` 等 |
| Linux | `~/.config/Tabbit` | 需用 `--app` 指定 |

- 脚本会自动探测平台 / 内核 / profile；探测失败时打印可用的 `--app` 指引。
- **Windows 专有坑**：Chromium 在 Windows 上使用 **app-bound 加密**（应用绑定加密），
  Cookie 依赖**可执行文件的身份** —— **必须用 Tabbit 自带的 `Tabbit.exe` 启动**才能解密，
  用 Chrome/Chromium 或裸 Playwright 内核都解不出。脚本已保证 `executablePath` 指向 `Tabbit.exe`。
- **务必先完全退出 Tabbit 应用**再运行脚本。

### 方式 C：一键导出并推送（可选）

`tools/refresh_fnos_token.mjs` 把「导出 Token → 登录面板 → 写入/更新 → 设 base_url → 刷新模型 → 验证」一条龙完成：

```bash
node tools/refresh_fnos_token.mjs
# 首次运行会提示输入「面板地址」和「admin 密码」，并记住到 ~/.tabbit2api-fnos.json，下次免输入
# 也可用参数/环境变量覆盖：--url --password --name --base（或 FNOS_URL / ADMIN_PW / TOKEN_NAME / BASE_URL）
```

面板地址支持省略 `http://` 与端口（自动补全为 `http://<host>:8800`），脚本无需写死 IP。

### 方式 D：手动解密 Cookie 数据库（进阶，不推荐）

Chromium 在 macOS 上用 Keychain 中的 `Tabbit Safe Storage` 派生密钥、AES-128-CBC、密文前缀 `v10`，IV 为 16 空格。
各版本 Tabbit 构建细节可能不同，**不建议手搓**；优先用方式 B。

---

## 三、添加与管理

- 管理面板 → **Tokens 管理**：可添加 / 删除 / 编辑 / 启停 Token；列表有「站点」列。
- **添加时务必选对站点**：选错站点会导致该 Token 在对应站点下「不可用」。
- 池中 Token 采用**加权轮询**，配合 `ACTIVE / COOLDOWN / BANNED` 状态机做健康管理：某个 Token 连续出错会进入冷却期，自动切换其它 Token。
- 可选配置 `encryption_key`（见 `config.json` 的 `agent.token_pool`），用 Fernet 加密存储 Token。

## 四、常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 返回 `请先登录`（401）/ 「missing token」 | Token 与当前站点不匹配 —— 切到对应站点，或把 Token 加到正确站点下 |
| 返回「浏览器版本过低」(code 493) | 缺 anti-bot 头或客户端协议过旧；用当前脚本导出的 Token 即可 |
| 返回 `code 492`「仅高级用户可用」 | 该模型是会员档（premium），账号无会员 —— 属预期，非故障 |
| Token 突然失效 | JWT 过期（约 7 天），重新导出即可 |
| 脚本读到 0 个 cookie / 明明登录了却「未找到 token」 | Playwright 默认 `--use-mock-keychain` 用假钥匙串，读不出系统真实加密的 cookie。脚本已加 `ignoreDefaultArgs: ['--use-mock-keychain']`；若仍失败，确认已在**同一台机器**的 Tabbit 里登录过目标站点 |
| Windows 脚本报解密失败 | 必须用 Tabbit 自带的 `Tabbit.exe` 启动（见「跨平台说明」） |
| 多账号 / 多站点 | 每个账号单独导出一个 Token，在面板选对站点后加入 Token 池 |

> ⚠️ Token 等同账号凭证，请勿公开分享或提交到仓库。
