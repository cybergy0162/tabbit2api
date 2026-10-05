# 如何获取 Tabbit Access Token（保姆级教程）

> 目标：拿到一串 Token（粘贴到 Tabbit2API 管理面板），让服务能调用你的 Tabbit 账号。
> 照着做即可，不需要懂代码。

---

## 0. 先认识 3 个词（30 秒）

| 词 | 简单理解 |
|----|----------|
| **终端 / Terminal** | macOS 上那个黑色窗口，用来敲命令。按 `⌘ + 空格` 搜 “Terminal” 或 “终端” 打开 |
| **仓库目录** | 你下载的 tabbit2api 源码文件夹（里面有 `tools` 这个子文件夹）。本教程用 `~/tabbit2api` 举例 |
| **Token** | 一串以 `eyJ...` 开头的长字符串，代表你的 Tabbit 登录身份 |

> ⚠️ 全文最容易踩的坑：**命令 `node tools/...` 里的 `tools` 是相对路径**，只在你「当前位于仓库目录」时才找得到。
> 所以每一步的「先 `cd` 到哪」都很重要，请照着抄。

---

## 1. 准备：装一次依赖（只做一次）

**① 确认你已经把源码放到了电脑上**，假设路径是：

```
~/tabbit2api
```

（如果你解压在别处，把下面所有 `~/tabbit2api` 换成你的实际路径。）

**② 打开终端，进入仓库目录：**

```bash
cd ~/tabbit2api
```

> 不知道自己放哪了？在 Finder 里进入该文件夹，按 `⌥ + ⌘ + C` 可复制路径，再 `cd` 过去。

**③ 安装依赖（装一次就够）：**

```bash
npm i -D playwright-core
```

看到 `added 1 package` 之类就成功了。
> 这一步会生成 `node_modules` 文件夹。依赖装在**仓库目录**里，脚本才能找到它。

**④ 确认 Node 已安装：**

```bash
node -v
```

能打印版本号（如 `v22.x`）即可。若提示 `command not found`，先装 Node（官网 nodejs.org 下载 LTS 版）。

---

## 2. 导出 Token（核心步骤）

### 第 1 步：完全退出 Tabbit 应用

先**彻底关闭** Tabbit（不是最小化）：
- macOS：菜单栏 `Tabbit` → `退出 Tabbit`，或按 `⌘ + Q`
- Windows：任务栏右键图标 → 退出

> 为什么要退出？脚本要复制 Tabbit 的登录数据，运行中的 Tabbit 会锁住它。

### 第 2 步：确认你已在 Tabbit 里登录了目标站点

打开 Tabbit，确认已登录：
- **国际版** → `https://web.tabbit.ai`
- **国内版** → `https://web.tabbit.com`

登录成功后再**退出 Tabbit**（回到第 1 步）。

### 第 3 步：回到仓库目录，运行脚本

**先确认你在仓库目录（重要！）：**

```bash
cd ~/tabbit2api
pwd
```

`pwd` 应该打印 `/Users/你的用户名/tabbit2api`。
如果打印的是别的（比如 `/Users/你的用户名`），说明你没进对目录 —— 上面的 `cd` 就是关键。

**然后运行：**

```bash
node tools/get_tabbit_token.mjs
```

成功时你会看到类似输出：

```
平台: darwin
内核: /Applications/Tabbit.app/Contents/MacOS/Tabbit
profile: /Users/xxx/Library/Application Support/Tabbit

=== Tabbit2API Token（粘贴到管理面板 Tokens 页）===
eyJhbGciOiJSUzI1NiIs...(一长串)...xCgOwJIpLtWEhtGUAMa5WadcV0
```

**最后那段 `eyJ...` 就是 Token** —— 全选复制它。

> 每次运行导出的 Token 都是有效的，直接用最新那条即可。

### （可选）导出国内版 Token

国内版用另一套参数：

```bash
node tools/get_tabbit_token.mjs \
  --site "https://web.tabbit.com" \
  --app "/Applications/Tabbit Browser.app/Contents/MacOS/Tabbit Browser" \
  --profile "$HOME/Library/Application Support/Tabbit Browser"
```

### 第 4 步：把 Token 粘贴到管理面板

1. 浏览器打开管理面板：`http://<你的服务器IP>:8800/admin`
2. 登录（默认密码 `admin`）
3. 进 **Tokens 管理** → **添加 Token**：
   - **名称**：随便起，如 `我的账号`
   - **站点**：⚠️ **选对**（国际版 / 国内版）—— 必须和刚才导出时的站点一致
   - **值**：粘贴刚才复制的 `eyJ...`
4. 保存 → 回到首页点「测试模型更新」，能看到模型列表就成功了。

> **Token 与站点绑定**：国际版导出的 Token 不能用到国内版，反之亦然。选错会显示「不可用」。

---

## 3. 一键脚本（懒人版，可选）

不想手动复制粘贴？用这个脚本，它自动帮你「导出 → 登录面板 → 写入 → 刷新模型 → 验证」：

```bash
cd ~/tabbit2api
node tools/refresh_fnos_token.mjs
```

- 第一次会问你要**面板地址**和 **admin 密码**，并记住，下次不用再输。
- 面板地址可以只写 IP，如 `192.168.1.102`，脚本会自动补成 `http://192.168.1.102:8800`。

---

## 4. 常见问题

| 现象 | 原因 / 怎么办 |
|------|----------------|
| `Cannot find module '.../tools/get_tabbit_token.mjs'` | **你在错的目录**。先 `cd ~/tabbit2api` 再跑；或改用绝对路径 `node ~/tabbit2api/tools/get_tabbit_token.mjs` |
| `Cannot find package 'playwright-core'` | 依赖没装，或装错了目录。在**仓库目录**里执行 `npm i -D playwright-core` |
| 脚本报「未找到 token Cookie」 | ① 没在 Tabbit 里登录目标站点；② 登录的站点和 `--site` 不一致；③ Tabbit 没完全退出 |
| 明明登录了却读到 0 个 cookie | 脚本已内置处理（去掉 `--use-mock-keychain`）。若仍失败，确认是在**同一台电脑**的 Tabbit 里登录过 |
| Windows 报解密失败 | Windows 必须用 Tabbit 自带的 `Tabbit.exe` 启动（脚本已自动探测） |
| 服务器返回「浏览器版本过低」(code 493) | 用最新脚本重新导出 Token 即可 |
| 服务器返回「仅高级用户可用」(code 492) | 该模型是会员专属，你的账号没会员 —— 属正常，不是故障 |
| Token 突然用不了 | JWT 约 **7 天**过期，重新跑一次导出、更新到面板即可 |
| 管理面板显示「missing token」/ 401 | Token 与当前站点不匹配 —— 切到对应站点，或把 Token 加到正确站点下 |

---

## 附录 A：Windows 用户

1. 装 Node（nodejs.org 下 LTS）。
2. 打开 **PowerShell**（不是 CMD），进入仓库目录：
   ```powershell
   cd $HOME\tabbit2api
   npm i -D playwright-core
   ```
3. 完全退出 Tabbit，然后：
   ```powershell
   node tools\get_tabbit_token.mjs
   ```
4. 若脚本探测不到 Tabbit 安装位置，手动指定：
   ```powershell
   node tools\get_tabbit_token.mjs --app "$env:LOCALAPPDATA\Programs\Tabbit\Tabbit.exe"
   ```
5. 国内版追加 `--site "https://web.tabbit.com"`。

> Windows 专有坑：Tabbit 的 Cookie 用「应用绑定加密」，**必须用 Tabbit 自带的 `Tabbit.exe` 启动**才能解密，脚本已自动处理。

## 附录 B：Linux 用户

profile 与内核路径因发行版而异，一般需手动指定：

```bash
cd ~/tabbit2api
npm i -D playwright-core
node tools/get_tabbit_token.mjs --app "/path/to/Tabbit" --profile "$HOME/.config/Tabbit"
```

---

## 附录 C：各平台默认路径速查

| 平台 | profile 默认位置 | 内核 |
|------|------------------|------|
| macOS | `~/Library/Application Support/Tabbit` | `/Applications/Tabbit.app/Contents/MacOS/Tabbit`（自动） |
| Windows | `%LOCALAPPDATA%\Tabbit\User Data` 等 | `%LOCALAPPDATA%\Programs\Tabbit\Tabbit.exe`（自动） |
| Linux | `~/.config/Tabbit` | 用 `--app` 指定 |

---

## 附录 D：进阶——手动从浏览器复制（不推荐）

部分站点在标准浏览器登录时，可以手动取：

1. 打开开发者工具（F12 / `⌥⌘I`）→ **Application / 应用** → **Cookies**。
2. 选目标站点域名，找到名为 `token` 的项，复制 Value。
3. 但实测 `token` 是 **HttpOnly**，Console 里 `document.cookie` 看不到，且不少站点在标准浏览器不触发登录 —— **所以优先用脚本**。

> Token 等同账号凭证，请勿公开分享或提交到仓库。有效期约 7 天，过期重新导出即可。
