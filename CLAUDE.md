# 小红书爆款标题助手

为研生之力（Nervive）品牌生成小红书爆款标题，支持 Web 页面和飞书机器人两种入口。

## 技术栈

- **后端**: Python Flask
- **LLM**: DeepSeek API（`deepseek-chat`）
- **飞书**: 开放平台机器人，事件订阅 + 消息回复
- **部署**: 阿里云 ECS，Gunicorn 2 workers，systemd 管理
- **版本控制**: GitHub [jsyoyo/xhs-title-assistant](https://github.com/jsyoyo/xhs-title-assistant)

## 项目结构

```
.
├── app.py                  # Flask 主应用（Web 路由 + 飞书事件处理）
├── title_generator.py       # 标题生成引擎（LLM 调用 + 模板回退 + 合规检查）
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── CLAUDE.md                # 项目说明书（本文件）
├── knowledge/               # 产品知识库（Markdown，走 Git 管理）
│   ├── products.json        # 产品配置（id、名称、对应知识文件）
│   ├── product-info.md      # 超能B族产品信息
│   ├── product-info-ctj.md  # 巢天娇产品信息
│   ├── templates.md         # 爆款标题公式
│   ├── trending-slang.md    # 流行表达 & 开头钩子
│   ├── keywords-dict.md     # 关键词词典
│   └── forbidden-words.md   # 违禁词 & 合规替换表
└── templates/               # Flask 模板
    └── index.html           # Web 标题生成页面
```

## 架构

### 标题生成流程（两种模式）

**模式 1 — 文案取标题**：用户粘贴完整小红书文案 → LLM 分析人称视角/语气风格/核心卖点 → 生成匹配原风格的标题

**模式 2 — 视频配标题**：用户输入视频传播方向 → LLM 围绕产品生成标题

LLM 无 API Key 时自动回退到内置模板（`FALLBACK_*` 字典）。

### 飞书机器人流程

```
用户发消息 → 飞书推送事件到 /feishu/event
  → URL 验证？直接返回 challenge
  → 消息事件？检查 chat_type：
      - p2p（私聊）：直接处理
      - group（群聊）：检查 mentions 中是否有本机器人
  → 去重（event_id 记录在 _PROCESSED_EVENTS，超 200 条逐条淘汰）
  → 过滤机器人自己的消息（通过学习的 _BOT_OPEN_ID）
  → 异步线程调用 _process_feishu_message()
  → _parse_command() 解析：产品、格式（短/长）、数量、内容
  → generate_titles() 生成标题
  → _reply_feishu() 回复
```

### 关键函数说明

| 函数 | 文件 | 用途 |
|---|---|---|
| `generate_titles()` | title_generator.py | 主入口，调用 LLM 或模板 |
| `check_title()` | title_generator.py | 合规检查（违禁词、功效承诺、长度） |
| `_parse_command()` | app.py | 从飞书消息解析参数 |
| `feishu_event()` | app.py | 飞书事件入口 |
| `_process_feishu_message()` | app.py | 异步标题生成+回复 |

## 部署

### 服务器信息

- IP: 8.136.183.255
- 代码路径: `/home/xhsbot/xhs-title-bot/`
- 服务管理: `systemctl restart xhs-title-bot`
- Gunicorn: 2 workers, `gunicorn app:app -b 0.0.0.0:5100 -w 2 --timeout 120`
- 虚拟环境: `/home/xhsbot/xhs-title-bot/venv/`

### 部署流程

```
本地修改 → git commit → git push → 服务器 git pull → systemctl restart xhs-title-bot
```

服务器上代码不是 git 仓库（是直接拷贝部署的），更新需 curl 替换文件或重建 git 仓库。

## 工作约定

### 知识库管理
- 知识库文件在 `knowledge/` 目录，走 Git 版本控制
- 修改流程：本地编辑 Markdown → commit → push → 服务器更新
- 网页编辑器已下线，不要在服务器上直接改文件

### 安全
- `.env` 包含真实密钥，已在 `.gitignore` 中排除，永不提交
- `.docx` 文件不入库（审核表等二进制文件）
- 飞书密钥不打印到日志

## 当前进展

### 已完成
- [x] Flask Web 双模式标题生成
- [x] 飞书机器人 @触发标题生成
- [x] 违禁词合规检查 + 模板回退
- [x] 飞书群聊误触发修复（只响应 @机器人 的消息）
- [x] 事件去重优化（淘汰制替代全清空）
- [x] GitHub 仓库 + 阿里云部署
- [x] 网页编辑器下线，知识库走 Git

### 待推进
- [ ] 卡片式 UI 回复（优先级降低，暂缓）
- [ ] 知识库更新流程优化
- [ ] 标题点击率后效追踪
- [ ] 飞书文档 API 同步知识库（方案 C）
