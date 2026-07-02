# 洞见飞书小程序 — 部署指南

> 飞书小程序运行在飞书 App 内，通过 `tt.request()` 直接调本地 Flask API（`http://127.0.0.1:5000`），零网络依赖。

## 项目结构

```
~/dongjian-feishu/
├── app.js              # 入口，globalData.apiBase = 'http://127.0.0.1:5000'
├── app.json            # 页面注册 + 窗口配置
├── project.config.json # urlCheck: false（允许 localhost）
└── pages/index/
    ├── index.js        # 页面逻辑 — tt.request() 调 Flask API
    ├── index.json      # 页面配置
    ├── index.ttml      # 模板 — 双 Tab（分析 + 谈判）
    └── index.ttss      # 暗色主题样式（#0f1117）
```

## 部署步骤

### 1. Flask 端准备
Flask 已通过 `@app.after_request` 添加 CORS 头：
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Headers: Content-Type, Authorization
Access-Control-Allow-Methods: GET, POST, OPTIONS
```
无需额外配置。确保 `python3 daemon.py` 在运行。

### 2. 飞书开放平台注册
手机浏览器打开 https://open.feishu.cn → 登录 → 创建企业自建应用 → 选择「小程序」

### 3. 上传代码
- 在应用后台 →「小程序」→「开发管理」→ 上传 `dongjian-feishu.zip`
- zip 生成命令：`python3 -c "import zipfile,os; ..."`（Termux 无 zip 命令）

### 4. 配置服务器域名
- 「安全设置」→「服务器域名」→ request 合法域名 → 添加 `http://127.0.0.1:5000`
- **重要**：这是 localhost，飞书开发者工具预览时需在手机端飞书 App 打开（桌面模拟器无法访问手机 localhost）

### 5. 发布体验版
「发布」→「体验版」→ 设置体验成员 → 保存

### 6. 在飞书中使用
飞书 App → 工作台 → 搜索小程序名称 → 打开

## 预览方式

**方式一（推荐）：体验版发布**
上传代码后发布为体验版，飞书 App 内直接打开。

**方式二：飞书开发者工具 + USB 调试**
桌面安装飞书开发者工具 → 手机 USB 连接 → 工具内扫码预览。Android/Termux 环境无法运行桌面工具，故推荐方式一。

## API 调用示例

小程序通过 `tt.request()` 调本地 Flask：

```js
// 对话分析
tt.request({
  url: 'http://127.0.0.1:5000/api/analyze',
  method: 'POST',
  header: { 'Content-Type': 'application/json' },
  data: { conversation: '...', subject: '候选人' },
  success: (res) => { /* res.data 为纯文本 */ }
});

// 谈判策略
tt.request({
  url: 'http://127.0.0.1:5000/api/negotiate',
  method: 'POST',
  data: { question: '你们能给多少钱？' }
});
```

## 注意事项

- 小程序在飞书 App 内运行时，`127.0.0.1` 指向手机本机，前提是 Flask 在同一设备上运行
- 飞书小程序不支持流式 `tt.request` 响应（非流式，一次性返回），但 Flask 的 negotiate 端点响应仅 ~200-600B，无感知
- 小程序配置文件 `project.config.json` 中 `urlCheck: false` 允许非 HTTPS localhost 请求
- 首次使用需在飞书开放平台设置「服务器域名」白名单
