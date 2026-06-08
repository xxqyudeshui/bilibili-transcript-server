# 🎬 （More than）Bilibili Transcript MCP Server

<p align="center">
  <b>一键提取 Bilibili 视频英文原声文本并获取结构化笔记的 MCP 工具</b><br>
  <b>Extract English transcript from Bilibili videos via MCP</b>
</p>

<p align="center">
  <a href="#中文文档">中文</a> | <a href="#english-readme">English</a>
</p>

---

<!-- Badges -->
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/MCP-stdio-green?logo=claude" alt="MCP stdio" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT License" />
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey" alt="Platform" />
</p>

---

<a name="中文文档"></a>
## 🇨🇳 中文文档

### ✨ 功能特性

- 🔗 **支持任意 Bilibili 视频链接** — 自动解析 BV 号和分集（`p=2` 等）
- 📝 **双策略字幕提取** — 优先调用 Bilibili API 获取官方 CC 字幕，无字幕时自动 fallback 到本地 ASR
- 🛡️ **内置反爬虫绕过** — 自动携带浏览器 Headers，绕过 Bilibili HTTP 412 拦截
- 🧠 **本地 faster-whisper ASR** — 默认使用 `small` 模型，支持 `base` / `small` / `medium` 灵活切换
- 🔒 **纯本地运行** — 所有数据本地处理，无需上传视频到第三方云端服务
- 🎯 **MCP 原生集成** — 一句 `/mcp add` 即可挂载到 Claude Code，像调用原生工具一样使用

### 📖 用途说明

这个工具专为以下场景设计：

1. **学术视频学习** — 提取英文数学/物理/计算机讲座的字幕或语音文本，生成结构化笔记
2. **内容翻译与二次创作** — 快速获取视频原声文本，作为翻译或剪辑的底稿
3. **知识库构建** — 将 Bilibili 上的优质英文教程批量转录为可检索的文本存档

### 🔧 技术原理

#### 反爬虫机制处理

Bilibili 对非浏览器请求有严格的反爬策略，常见问题包括：

| 问题 | 解决方案 |
|------|----------|
| **SSL 证书验证失败** | 使用 `ssl._create_unverified_context()` 绕过 macOS 本地证书限制 |
| **HTTP 412 Precondition Failed** | 自动注入 `User-Agent` 和 `Referer` 请求头，模拟真实浏览器访问 |
| **WBI 签名验证** | 依赖 `yt-dlp` 内置的 Bilibili 提取器自动处理签名和加密参数 |

核心 Headers：
```python
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36...
Referer: https://www.bilibili.com
```

#### 语音识别（ASR）

```
Bilibili API 字幕探测
    │
    ├─ ✅ 有 CC 字幕 → 直接下载返回
    │
    └─ ❌ 无字幕 ──→ yt-dlp 下载最佳音轨 ──→ faster-whisper 本地转录
                                              │
                                              ├─ 默认模型: small (~466MB)
                                              ├─ 可选模型: base (~150MB) / medium (~1.5GB)
                                              └─ 设备: auto (优先 GPU / Apple Silicon)
```

**为什么选 faster-whisper？**
- 基于 CTranslate2 推理框架，比 OpenAI 原始 Whisper 快 **4-8 倍**
- 支持 `int8` 量化，MacBook 无显卡也能流畅运行
- 模型首次运行时自动从 HuggingFace 下载并缓存到本地 `models/` 目录

### 🚀 快速开始

#### 1. 克隆仓库

```bash
git clone https://github.com/xxqyudeshui/bilibili-transcript-server.git
cd bilibili-transcript-server
```

#### 2. 创建虚拟环境（强烈推荐）

```bash
python3 -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

#### 3. 安装依赖

```bash
pip install -r requirements.txt
```

第一次运行时会自动下载 faster-whisper 模型（`small` 约 466MB，视网速需 2-10 分钟）。

#### 4. 挂载到 Claude Code

**方式 A：命令行一键挂载（推荐）**

```bash
claude mcp add bilibili-transcript -- \
  "$(pwd)/venv/bin/python" \
  "$(pwd)/server.py"
```

**方式 B：手动编辑配置**

在 `~/.claude.json` 中添加：

```json
{
  "mcpServers": {
    "bilibili-transcript": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

**验证挂载**：
```bash
claude mcp list
# 应显示：bilibili-transcript: ✓ Connected
```

### 💬 使用示例

挂载成功后，在 Claude Code 对话中直接说：

> *"请用 get_video_transcript 提取 https://www.bilibili.com/video/BV1aJ411w74i/?p=2 的英文文本"*

Claude 会自动调用该工具，返回纯英文转录文本。

### ⚙️ 高级配置

#### 切换 Whisper 模型大小

```bash
# 启动前设置环境变量
export WHISPER_MODEL=base    # 更快，准确度稍低
export WHISPER_MODEL=medium  # 更准，需要 ~1.5GB 内存

# 然后重新挂载或运行
claude mcp add bilibili-transcript -- ./venv/bin/python ./server.py
```

#### 手动运行（不通过 MCP）

```bash
source venv/bin/activate
python -c "
from server import get_video_transcript
url = 'https://www.bilibili.com/video/BV1aJ411w74i/?p=2'
text = get_video_transcript(url)
print(text)
"
```

### 📁 项目结构

```
bilibili-transcript-server/
├── server.py           # MCP Server 主文件（核心代码）
├── requirements.txt    # Python 依赖清单
├── README.md           # 本文档
└── .gitignore          # Git 忽略规则（排除 venv/ models/ temp/）
```

### 🧪 已知限制

| 限制 | 说明 |
|------|------|
| **仅限英文** | 当前 ASR 强制 `language="en"`，中文视频效果不佳 |
| **无 CC 字幕时耗时较长** | ASR 转录速度约为实时 5-10 倍（20 分钟视频约需 2-4 分钟） |
| **会员/付费视频** | 受 Bilibili 权限控制，无法突破 |
| **模型首次下载** | 需从 HuggingFace 下载 ~466MB 模型，中国大陆用户可能需要代理 |

### 📜 许可证

MIT License — 自由使用、修改和分发。

---

<a name="english-readme"></a>
## 🇺🇸 English README

### ✨ Features

- 🔗 **Any Bilibili URL** — Auto-extracts BV ID and page numbers (`p=2`, etc.)
- 📝 **Dual-strategy transcript** — Tries official CC subtitles first, falls back to local ASR
- 🛡️ **Anti-bot bypass** — Built-in browser headers to circumvent Bilibili HTTP 412 blocks
- 🧠 **Local faster-whisper ASR** — Default `small` model, configurable to `base` / `medium`
- 🔒 **Fully local** — No video data ever leaves your machine
- 🎯 **Native MCP integration** — One `/mcp add` command to mount in Claude Code

### 🔧 How It Works

**Anti-bot handling**
- Injects `User-Agent` and `Referer` headers to mimic real browsers
- Uses `yt-dlp`'s built-in Bilibili extractor for WBI signature handling

**ASR Pipeline**
```
Bilibili API subtitle check
    │
    ├─ ✅ Subtitles found → Download and return
    │
    └─ ❌ No subtitles ──→ yt-dlp downloads audio ──→ faster-whisper transcribes locally
```

### 🚀 Quick Start

```bash
git clone https://github.com/xxqyudeshui/bilibili-transcript-server.git
cd bilibili-transcript-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Mount in Claude Code:**
```bash
claude mcp add bilibili-transcript -- ./venv/bin/python ./server.py
```

**Verify:**
```bash
claude mcp list
# bilibili-transcript: ✓ Connected
```

### 💬 Usage

Once mounted, ask Claude:
> *"Use get_video_transcript to extract the English text from https://www.bilibili.com/video/BV1aJ411w74i/?p=2"*

### ⚙️ Configuration

Switch whisper model via environment variable:
```bash
export WHISPER_MODEL=base    # faster, less accurate
export WHISPER_MODEL=medium  # slower, more accurate (~1.5GB)
```

### 📜 License

MIT License

---

<p align="center">
  Made with ❤️ for academic knowledge flow
</p>
