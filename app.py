#!/usr/bin/env python3
"""
洞见 (DongJian) — 人才风险分析 Web 应用
Flask 后端，提供对话分析和谈判策略两个模块
"""

import os
import json
import re
import sys
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory, Response, stream_with_context

app = Flask(__name__)

# ── CORS（支持飞书小程序等跨域请求）──
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# ── 配置 ──────────────────────────────────────────────
# 知识库路径：优先使用项目内置 knowledge_base/，回退到 Hermes skills 路径
_KB_LOCAL = Path(__file__).parent / "knowledge_base"
_KB_HERMES = Path(__file__).parent.parent / ".hermes" / "skills" / "dongjian" / "dongjian" / "references"
KNOWLEDGE_BASE = _KB_LOCAL if _KB_LOCAL.exists() else _KB_HERMES

# 自动加载 ~/.hermes/.env 中的 Key
def _load_env_file(path: str) -> None:
    """从 .env 文件加载环境变量（不覆盖已有的）"""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass

_load_env_file(os.path.expanduser("~/.hermes/.env"))

LLM_API_KEY = os.environ.get("LLM_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2560"))
LLM_NEGOTIATE_MAX_TOKENS = int(os.environ.get("LLM_NEGOTIATE_MAX_TOKENS", "2048"))

# ── 知识库加载 ─────────────────────────────────────────
KB_FILES = {
    "language": "language-fingerprints.md",
    "behavior": "behavioral-patterns.md",
    "risk": "risk-signals.md",
    "situational": "situational-logic.md",
    "negotiation": "negotiation-strategies.md",
    "company_values": "company-values.md",
    "communication": "communication-classics.md",
    "labor_law": "labor-law.md",
    "embodied_ai": "embodied-ai.md",
}

def load_knowledge_base() -> dict[str, str]:
    kb = {}
    for key, filename in KB_FILES.items():
        fp = KNOWLEDGE_BASE / filename
        if fp.exists():
            kb[key] = fp.read_text(encoding="utf-8")
        else:
            kb[key] = f"(知识库文件未找到: {filename})"
    return kb

# ── LLM 调用 ──────────────────────────────────────────
def call_llm(system_prompt: str, user_prompt: str) -> str:
    """调用 LLM API 进行分析（非流式，收集完整响应）"""
    chunks = list(call_llm_stream(system_prompt, user_prompt))
    return "".join(chunks) if chunks else _no_api_key_response()

def call_llm_stream(system_prompt: str, user_prompt: str, max_tokens: int = None):
    """流式调用 LLM API，逐块返回"""

    if max_tokens is None:
        max_tokens = LLM_MAX_TOKENS

    import urllib.request
    import urllib.error

    if not LLM_API_KEY:
        yield _no_api_key_response()
        return

    if max_tokens is None:
        max_tokens = LLM_MAX_TOKENS

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": True,
    }).encode("utf-8")

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    })

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for line in resp:
                line = line.decode("utf-8", errors="replace").strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        yield f"\n❌ LLM API 错误 ({e.code}): {err_body[:500]}"
    except Exception as e:
        yield f"\n❌ 请求失败: {str(e)}"

def _no_api_key_response() -> str:
    return """⚠️ 未配置 API Key。"""

# ── 系统提示词构建 ─────────────────────────────────────
def build_analysis_system_prompt(kb: dict[str, str]) -> str:
    # 优先使用精简版知识库（约4KB vs 43KB完整版）
    condensed_path = KNOWLEDGE_BASE / "kb-condensed.md"
    if condensed_path.exists():
        kb_core = condensed_path.read_text(encoding="utf-8")
    else:
        # 回退到完整模块
        kb_core = f"""## 语言指纹\n{kb.get('language', '')}\n## 行为模式\n{kb.get('behavior', '')}\n## 风险信号\n{kb.get('risk', '')}\n## 情景逻辑\n{kb.get('situational', '')}\n## 公司素质\n{kb.get('company_values', '')}\n## 沟通经典\n{kb.get('communication', '')}\n## 劳动法\n{kb.get('labor_law', '')}\n## 具身智能\n{kb.get('embodied_ai', '')}"""

    return f"""你是「洞见」(DongJian) 人才风险分析专家。你基于心理学文献训练，专长从对话记录中提取语言指纹和行为模式，推断候选人的动机、性格特质、潜在风险。

## 知识库

{kb_core}

## 分析要求

请按以下格式输出。第一部分为决策摘要（优先展示），第二部分用 `[DETAILS]` 标记分隔，为详细分析过程。

═══════════════════════════════════════════
          洞见分析报告 — [对象代号]
═══════════════════════════════════════════

📊 风险矩阵
┌──────────┬──────┬──────┬──────────────────────┐
│ 风险类型  │ 等级  │ 置信度│ 关键信号              │
├──────────┼──────┼──────┼──────────────────────┤
│ 诚信风险  │ ...  │ ...  │ ...                  │
│ 稳定性    │ ...  │ ...  │ ...                  │
│ 适配风险  │ ...  │ ...  │ ...                  │
│ 离职风险  │ ...  │ ...  │ ...                  │
│ 权力动机  │ ...  │ ...  │ ...                  │
└──────────┴──────┴──────┴──────────────────────┘

🏢 公司软性素质匹配
┌──────────────────────┬──────┬──────┬──────────────────────┐
│ 素质维度               │ 评分  │ 置信度│ 关键证据              │
├──────────────────────┼──────┼──────┼──────────────────────┤
│ 实事求是               │ 🟢🟡🔴│ X%   │ ...                  │
│ 追求极致               │ 🟢🟡🔴│ X%   │ ...                  │
│ 思考力                 │ 🟢🟡🔴│ X%   │ ...                  │
│ 持续学习               │ 🟢🟡🔴│ X%   │ ...                  │
│ 会抓重点               │ 🟢🟡🔴│ X%   │ ...                  │
│ 技术品味与行业认知      │ 🟢🟡🔴│ X%   │ ...                  │
├──────────────────────┼──────┼──────┼──────────────────────┤
│ 综合匹配度             │ X/6  │ —    │ 关键短板: [...]       │
└──────────────────────┴──────┴──────┴──────────────────────┘

🔍 追问建议（3-5条具体可操作的追问方向）

[DETAILS]

一、动机画像
  核心驱动力: [成就/权力/归属/安全] (主导+次要)
  信心度: [高/中/低]
  依据: [...]

二、人格特征（大五人格 OCEAN）
  开放性: [高/中/低] (置信度: X%)
  尽责性: [高/中/低] (置信度: X%)
  外向性: [高/中/低] (置信度: X%)
  宜人性: [高/中/低] (置信度: X%)
  神经质: [高/中/低] (置信度: X%)

三、暗黑三角
  自恋: [低/中/高]  马基雅维利: [低/中/高]  精神病态: [低/中/高]

四、归因风格
  模式: [内控/外控 + 稳定/不稳定]  证据: [...]

五、关键证据引用
  信号N: "[原句]" → 维度: [X]，含义: [Y]

六、自校准标注
  偏误: [...]  不确定性: [...]

注意事项:
- 中文高语境文化中的人称代词省略、填充词不可过度解读
- 策略性谈判行为不等于马基雅维利人格
- 单一对话片段信息有限，降低对应维度的置信度
- 分析基于统计学模式，提供参考而非绝对判断
- 如涉及辞退/离职场景，可参考劳动法知识库中的法律框架进行合规性分析
"""

def build_refine_system_prompt(kb: dict[str, str]) -> str:
    return f"""你是「洞见」(DongJian) 谈判策略顾问。现在进入了多轮博弈优化模式——用户已经看过你之前给出的策略，并提出了具体的反馈意见。你的任务是根据反馈，调整和优化策略。

## 谈判知识库
{kb.get('negotiation', '')}

## 输出要求

请输出优化后的完整策略（不是只改一小段，而是给出完整的修订版），但对用户反馈指出的问题要在对应部分明确标注「已优化」或说明调整了什么。

保持原模板格式：

═══════════════════════════════════════════
          洞见谈判策略（已优化）
═══════════════════════════════════════════

一、深层需求解码
  表面问题: [...]
  实际担忧: [...]
  调整说明: [根据反馈做了什么修正]

二、策略选项（三条路径）
  🔴 硬策略: [...]
  🟢 软策略: [...]
  🔵 原则策略: [...]

三、推荐方案
  推荐策略: [...]
  核心话术: "[...]"

四、备用筹码
  · [...]

五、风险提示
  - [...]
═══════════════════════════════════════════

重要原则:
- 如果用户反馈指出策略太软，就强化硬策略路径
- 如果用户反馈指出策略太硬，就增加关系建设维度
- 如果用户提供了新信息（如候选人反应、新报价），务必结合新信息调整
- 不要防御性地为原策略辩护，而是真诚地根据反馈优化
- 如果用户指出的问题确实存在，直接承认并给出更好的方案
"""


def build_negotiation_system_prompt(kb: dict[str, str]) -> str:
    # 使用完整谈判知识库（HF 部署无超时限制）
    negotiation_kb = kb.get('negotiation', '')

    return f"""你是「洞见」(DongJian) 谈判策略顾问。你基于谈判心理学（Cialdini影响力、Fisher & Ury原则谈判、Malhotra谈判天才）、认知偏差和说服理论，为HR/招聘人员提供应对候选人质疑的策略。

## 谈判知识库

{negotiation_kb}

## 候选人画像参考（如有先前的分析结果，会附在用户消息中）

## 输出要求

请严格按照以下模板输出完整的谈判策略分析。使用中文。

═══════════════════════════════════════════
          洞见谈判策略
═══════════════════════════════════════════

一、深层需求解码

  候选人原话: "[复述]"

  表面问题: [对方在问什么]

  ┌─────────────────────────────────────────┐
  │ 实际三层诉求:                            │
  │ ① [第一层]: [...]                       │
  │ ② [第二层]: [...]                       │
  │ ③ [第三层]: [...]                       │
  └─────────────────────────────────────────┘

  关键陷阱识别: [这个问题里藏着什么框架绑架/认知陷阱]

二、策略选项（三条独立路径，每条包含完整话术）

  🔴 策略A（硬 — 对抗/锚定）:
     · 核心逻辑: [...]
     · 完整话术: "[可直接使用的措辞，2-4句]"
     · 博弈分析: [为什么这个策略可能有效]
     · ⚠️ 风险: [...]

  🟢 策略B（软 — 关系/情感）:
     · 核心逻辑: [...]
     · 完整话术: "[可直接使用的措辞，2-4句]"
     · 博弈分析: [为什么这个策略可能有效]
     · ⚠️ 风险: [...]

  🔵 策略C（原则 — 价值共创/框架重构）:
     · 核心逻辑: [...]
     · 完整话术: "[可直接使用的措辞，2-4句]"
     · 博弈分析: [为什么这个策略可能有效]
     · ⚠️ 风险: [...]

三、推荐方案

  推荐策略: [选A/B/C]

  推荐理由（结合候选人画像和博弈逻辑）:
  [2-3句话说明为什么选这个]

  核心话术（可直接复制使用）:
  ┌─────────────────────────────────────────┐
  │ "[完整话术，可直接使用]"                  │
  └─────────────────────────────────────────┘

  博弈逻辑图:
  [简要描述你出牌后，对方可能的几种反应，以及你的应对预案]

四、备用筹码（优先级排序）

  · [筹码1]: [说明为什么有效]
  · [筹码2]: [说明为什么有效]
  · [筹码3]: [说明为什么有效]

五、风险提示

  ⚠️ 该策略的潜在后坐力: [...]

  ⚠️ 信号识别与策略切换:
    如果候选人出现 [X信号]，则应立即调整策略为 [Y]

  ⚠️ 底线: [什么情况下应该放弃谈判]

═══════════════════════════════════════════

重要原则:
- 对人温和，对事强硬
- 永远不要在他的棋盘上下棋，要重新定义游戏规则
- 薪资谈判的核心：把单一数字扩展为多维价值
- 最好的谈判是双方都觉得自己赚了
- 谈判中的策略性行为不等于马基雅维利人格
- 如涉及辞退/离职谈判，务必参考劳动法知识库（解除类型、补偿金计算N/N+1/2N、合法程序）确保合规"""

# ── API 路由 ──────────────────────────────────────────
@app.route("/")
def index():
    response = app.make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True)
    conversation = data.get("conversation", "").strip()
    subject = data.get("subject", "候选人").strip()

    if not conversation:
        return jsonify({"error": "请提供对话记录"}), 400

    kb = load_knowledge_base()
    system_prompt = build_analysis_system_prompt(kb)
    user_prompt = f"请分析以下对话记录。对象代号: {subject}\n\n对话记录:\n{conversation}"

    return Response(
        stream_with_context(call_llm_stream(system_prompt, user_prompt)),
        mimetype="text/plain; charset=utf-8"
    )

@app.route("/api/negotiate", methods=["POST"])
def negotiate():
    data = request.get_json(force=True)
    question = data.get("question", "").strip()
    profile = data.get("profile", "").strip()
    context = data.get("context", "").strip()

    if not question:
        return jsonify({"error": "请提供候选人的质疑内容"}), 400

    kb = load_knowledge_base()
    system_prompt = build_negotiation_system_prompt(kb)

    user_prompt = f"候选人对我说了以下话:\n\n\"{question}\"\n\n"
    if profile:
        user_prompt += f"候选人画像参考:\n{profile}\n\n"
    if context:
        user_prompt += f"额外背景:\n{context}\n\n"
    user_prompt += "请给我谈判策略。"

    return Response(
        stream_with_context(call_llm_stream(system_prompt, user_prompt, LLM_NEGOTIATE_MAX_TOKENS)),
        mimetype="text/plain; charset=utf-8"
    )


@app.route("/api/negotiate/refine", methods=["POST"])
def negotiate_refine():
    """多轮博弈：基于用户反馈优化谈判策略"""
    data = request.get_json(force=True)
    original_strategy = data.get("strategy", "").strip()
    feedback = data.get("feedback", "").strip()
    history = data.get("history", "").strip()

    if not original_strategy or not feedback:
        return jsonify({"error": "请提供原始策略和反馈意见"}), 400

    kb = load_knowledge_base()
    system_prompt = build_refine_system_prompt(kb)

    user_prompt = f"## 原始策略\n{original_strategy}\n\n## 我的反馈\n{feedback}"
    if history:
        user_prompt += f"\n\n## 之前的反馈历史\n{history}"
    user_prompt += "\n\n请基于我的反馈，输出优化后的完整谈判策略。"

    return Response(
        stream_with_context(call_llm_stream(system_prompt, user_prompt, LLM_NEGOTIATE_MAX_TOKENS)),
        mimetype="text/plain; charset=utf-8"
    )


@app.route("/api/analyze/chat", methods=["POST"])
def analyze_chat():
    """交互反馈：基于用户对分析报告的反馈，进一步深挖或调整判断"""
    data = request.get_json(force=True)
    report = data.get("report", "").strip()
    question = data.get("question", "").strip()
    conversation = data.get("conversation", "").strip()
    history = data.get("history", [])

    if not question:
        return jsonify({"error": "请提供反馈问题"}), 400

    kb = load_knowledge_base()
    condensed_path = KNOWLEDGE_BASE / "kb-condensed.md"
    kb_core = condensed_path.read_text(encoding="utf-8") if condensed_path.exists() else ""

    # 构建对话历史
    history_text = ""
    if history:
        history_text = "\n## 对话历史\n"
        for h in history[-6:]:  # 最近6轮
            role = "用户" if h.get("role") == "user" else "洞见"
            history_text += f"\n{role}: {h.get('content', '')[:300]}"

    system_prompt = f"""你是「洞见」交互分析顾问。用户已经看过一份候选人的分析报告，现在正在和你进行多轮对话来深入探讨和矫正分析。
{history_text}

## 知识库
{kb_core}

## 要求
- 这是一个持续对话，你的回答应该基于之前已经讨论过的内容
- 直接回答用户问题，不需要重复完整报告
- 如果用户指出某个判断有偏差，承认并给出修正后的分析，明确说明「原判断: ... → 修正: ...」
- 如果用户要求深挖某个维度，聚焦该维度展开详细分析
- 如果用户提供了新信息，结合新信息调整结论
- 简洁有力，300字以内"""

    user_prompt = f"## 原始对话\n{conversation}\n\n## 分析报告\n{report}\n\n## 用户最新问题\n{question}"

    return Response(
        stream_with_context(call_llm_stream(system_prompt, user_prompt)),
        mimetype="text/plain; charset=utf-8"
    )


@app.route("/api/health", methods=["GET"])
def health():
    kb = load_knowledge_base()
    kb_status = {k: "✓" if not v.startswith("(知识库") else "✗" for k, v in kb.items()}
    return jsonify({
        "status": "ok",
        "has_api_key": bool(LLM_API_KEY),
        "model": LLM_MODEL,
        "knowledge_base": kb_status,
    })

# ── 静态文件 ──────────────────────────────────────────
@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# ── 网络工具 ──────────────────────────────────────────
def get_lan_ip() -> str | None:
    """获取设备局域网 IP（通过 UDP 套接字检测）"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "127.0.0.1":
            return ip
    except Exception:
        pass
    return None

def get_wifi_ssid() -> str | None:
    """获取当前连接的 WiFi SSID（Android Termux）
    优先使用环境变量 DONGJIAN_WIFI_SSID，其次尝试 dumpsys 检测
    """
    # 环境变量覆盖
    env_ssid = os.environ.get("DONGJIAN_WIFI_SSID", "").strip()
    if env_ssid:
        return env_ssid
    # 尝试 dumpsys
    import subprocess
    try:
        out = subprocess.check_output(
            ["/system/bin/dumpsys", "wifi"],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode("utf-8", errors="replace")
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("SSID: "):
                ssid = line.split("SSID: ", 1)[1].strip().strip('"')
                if ssid and ssid != "<unknown ssid>":
                    return ssid
            if "mWifiInfo" in line and "SSID:" in line:
                ssid = line.split("SSID: ", 1)[1].split(",")[0].strip().strip('"')
                if ssid and ssid != "<unknown ssid>":
                    return ssid
    except Exception:
        pass
    return None

def start_ngrok(port: int) -> str | None:
    """启动 ngrok 隧道，返回公网 URL"""
    token = os.environ.get("NGROK_AUTH_TOKEN", "")
    if not token:
        return None
    try:
        from pyngrok import ngrok, conf
        conf.get_default().auth_token = token
        tunnel = ngrok.connect(port, "http")
        return tunnel.public_url
    except Exception as e:
        print(f"  ngrok 隧道启动失败: {e}")
        return None

# ── 启动 ──────────────────────────────────────────────
if __name__ == "__main__":
    kb = load_knowledge_base()
    loaded = sum(1 for v in kb.values() if not v.startswith("(知识库"))
    lan_ip = get_lan_ip()
    wifi_ssid = get_wifi_ssid()

    print("═" * 55)
    print("  洞见 (DongJian) — 人才风险分析 Web 应用")
    print("═" * 55)
    print(f"  知识库: {loaded}/{len(kb)} 个模块已加载")
    print(f"  LLM: {LLM_MODEL}")
    print(f"  API Key: {'已设置' if LLM_API_KEY else '未设置 ⚠️'}")
    print("─" * 55)
    print("  本机访问:")
    print(f"    http://127.0.0.1:5000")
    if lan_ip:
        wifi_info = f" (WiFi: {wifi_ssid})" if wifi_ssid else ""
        print(f"  LAN 分享{wifi_info}:")
        print(f"    http://{lan_ip}:5000")

    # 尝试启动 ngrok
    public_url = start_ngrok(5000)
    if public_url:
        print(f"  公网分享 (任何人可访问):")
        print(f"    {public_url}")
    else:
        print(f"  公网分享: 未配置 NGROK_AUTH_TOKEN (可选)")
        print(f"    注册 https://ngrok.com 获取免费 token")
        print(f"    export NGROK_AUTH_TOKEN='...' 后重启即可")

    print("═" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)
