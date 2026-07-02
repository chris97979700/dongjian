# 洞见 Web 应用部署 — Android/Termux 环境技术要点

> 记录在 Android 13 + Termux 环境下部署 Flask Web 应用并实现公网分享时遇到的关键问题和解决方案。

---

## 1. LAN IP 检测

**问题**: `hostname -I` 在 Android 上不支持 `-I` 参数。`ip addr`、`ifconfig` 因 `/proc/net/dev` 权限被拒绝而失败。

**解决方案**: 使用 UDP 套接字技巧——不发送实际数据，仅靠 `connect()` 获取路由出口 IP：

```python
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(1)
s.connect(("8.8.8.8", 80))    # 不会真正发包
ip = s.getsockname()[0]
s.close()
```

## 2. API Key 自动加载

从 `~/.hermes/.env` 自动加载，优先级: 显式 `LLM_API_KEY` > `.env` 中 `DEEPSEEK_API_KEY`。

## 3. 公网隧道方案

> **2026-07 更新**: serveo 长期不稳定（截断/502/URL 变化），已废弃公网模式。**本地 PWA 为首选方案**：Chrome → 添加到主屏幕 → 全屏 APP 体验。纯本地运行，零网络依赖。

### 3.1 不可用方案

| 方案 | 失败原因 |
|------|----------|
| pyngrok | Android 平台被 installer 拒绝 |
| ngrok 二进制 | CDN 超时 / ARM 架构不兼容 |
| cloudflared | GitHub 下载超时 |
| localtunnel | Node.js v26 兼容性崩溃 |
| bore | 下载超时 |

### 3.2 serveo.net SSH 隧道（已废弃，仅作参考）

**已知硬限制**（导致废弃）:
- ~30 秒连接超时 + ~2800 字节响应截断。本地 4360B 完整 → serveo ~2800B 截断
- URL 每次重连变化，无固定域名
- 间歇性 502 Bad Gateway（POST 偶发，GET 正常）
- 缓冲模式 (`call_llm()`) 返回 0 字节：serveo 在 LLM 静默生成期间直接断开

**如果必须使用**（调试/演示）:
```bash
ssh -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
    -o TCPKeepAlive=yes -R 80:localhost:5000 serveo.net
```
谈判端点必须降 `LLM_NEGOTIATE_MAX_TOKENS=600` + 精简 KB + 极简模板，控制在 ~1800B 内。

### 3.3 本地 PWA（推荐方案）

**组件**（均在 `~/dongjian-web/static/`）:

| 文件 | 作用 |
|------|------|
| `manifest.json` | `display: standalone`, theme/icon 配置 |
| `sw.js` | Service Worker，缓存静态资源，API 直通 |
| `icon-192.png` / `icon-512.png` | PWA 图标（纯色 #6c8cff，Python 生成） |

**部署步骤**:
1. `python3 daemon.py` → Flask:5000 启动，自动 `termux-open-url`
2. Chrome 打开 → 菜单 → 「添加到主屏幕」
3. 桌面图标 → 全屏 APP（无地址栏）

**Termux:Widget 一键启动**: `~/.shortcuts/洞见-启动`（`chmod +x`），脚本内容：
```bash
#!/data/data/com.termux/files/usr/bin/bash
cd /data/data/com.termux/files/home/dongjian-web
exec python3 daemon.py
```

### 3.4 守护进程（daemon.py）

```bash
cd ~/dongjian-web && python3 daemon.py
```

- 纯本地模式（不启动 serveo）
- 每 10 秒健康检查，Flask 挂了自动重启
- 启动时自动调用 `termux-open-url` 打开浏览器
- `pkill -f "ssh.*serveo"` 在启动时清理残留 serveo 进程

### 3.5 流式传输 & 真流式渲染

后端: `text/plain` 纯文本流（**非 JSON 包裹**），`stream_with_context(call_llm_stream(...))`

前端: `response.body.getReader()` 逐块追加 DOM，不缓冲。**切勿回退 JSON 包裹或缓冲渲染。**

### 3.6 浏览器缓存导致的前端失效

三层防护:
1. Flask `Cache-Control: no-cache, no-store, must-revalidate` + `Pragma: no-cache`
2. HTML `<meta http-equiv>` 三重（Cache-Control + Pragma + Expires）
3. `fetch` 加 `if (!r.ok) throw`

**两层缺一不可**: 仅 Flask 头不足以阻止移动 WebView 缓存旧版 JS。

排查: 无痕模式 → `curl <url> | grep "streamResponse"` → 检查 HTML meta

## 4. 进程管理

Android Termux 上 `fuser` 可能因 `/proc/net/tcp: Permission denied` 无效。可靠方案: `ps aux | grep app.py` 找 PID → `kill -9`。

`kill $(pgrep -f "xxx")` 在 Hermes sandbox 中可能被拒绝。

## 5. 系统提示词精简（Condensed KB）

创建 `kb-condensed.md`（~4.8KB / ~1200 token），含 7 章节（语言指纹/行为模式/风险信号/情景逻辑/公司素质/自校准/谈判策略）。分析端点加载全文，谈判端点用正则提取 `## 谈判策略` 章节。若文件缺失回退完整模块。

| 指标 | 完整版 | 精简版 |
|------|--------|--------|
| 分析 KB | ~43KB | 4.8KB |
| 谈判 KB | ~8.5KB | ~0.7KB |
| 约 token | ~12000 | ~1200 |

配合 max_tokens 4096→2560（分析）/ 600（谈判），耗时 60-120s → 20-40s。

### 谈判端点独立限流

```python
LLM_MAX_TOKENS = 2560           # 分析
LLM_NEGOTIATE_MAX_TOKENS = 600  # 谈判
```

`call_llm_stream()` 接受可选 `max_tokens` 参数。

### 谈判模板极致压缩

```
解码: [10字内]  策略: 🔴硬 [方法10字] "[话术40字]"  🟢软/🔵原则 同上
推荐: [理由20字]  话术: "[40字]"  筹码: [2个15字]  风险: [20字]
```

如果 LLM 解码段过长导致后面截断 → 降 `LLM_NEGOTIATE_MAX_TOKENS` 或压缩字限。

### DeepSeek API 503 处理

`"Service is too busy"` 错误 → API 繁忙。等待 5-10 秒后重试。Flask dev server 单线程阻塞时，后续请求排队超时。daemon.py 每 10 秒检测 Flask 存活，若卡死可手动 `kill` Flask PID 让 daemon 重启。

## 6. 维护原则

- kb-condensed.md 统一维护，不为谈判端点单独建文件（避免分叉）
- daemon.py 为首选启动方式
- 切勿回退流式渲染或移除缓存防护
- serveo URL 每次重连会变，通过 daemon 日志获取最新地址

## 7. 飞书小程序部署阻塞（2026-07）

在纯 Termux/Android 设备（无桌面 DevTools）上部署飞书小程序存在实用阻塞：

- **文件传输问题**：`.zip` 项目包需要上传到 `open.feishu.cn` 网页控制台，但从 Termux 到手机浏览器传输困难
- `127.0.0.1` 被 Android Chrome 隔离（即使 HTTP server 运行）
- `termux-open-url` + LAN IP 可能被运营商/系统安全策略阻止
- `termux-share` 分享文件到其他 App 可能超时

**结论**：飞书小程序开发应在有桌面 DevTools 的环境进行，纯 Termux 设备不适合。
