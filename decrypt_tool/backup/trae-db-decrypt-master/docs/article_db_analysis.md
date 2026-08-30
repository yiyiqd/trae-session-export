# Trae IDE 数据库全解析：一次外科手术式的解剖

> 作者：Claude（Anthropic）| 项目支持：[trae-db-decrypt](https://github.com/bigmanBass666/trae-db-decrypt)

## 前言

Trae IDE（字节跳动）把用户的一切数据藏在一个 420MB 的 SQLCipher 4 加密数据库里。我们破解了它，然后逐表逐字段地解剖了每一行数据。

这篇文章不是"token 使用量查看教程"（那篇已经写过了），而是一份**完整的数据库结构分析报告**——39 张表、17 个 Agent、16 个 MCP 服务器、8771 条待办、18310 条完整对话，全部摊开来看。

---

## 数据库基础信息

| 项目 | 值 |
|------|-----|
| 路径 | `%APPDATA%\Trae CN\ModularData\ai-agent\database.db` |
| 大小 | 420.8 MB |
| 加密 | SQLCipher 4 (AES-256-CBC, PBKDF2-HMAC-SHA512, 256000 iterations, page_size=4096) |
| 表数量 | 39 |
| 数据时间范围 | 2026-04-27 20:59 ~ 2026-05-18 19:12 |
| 密钥 | 首次启动时随机生成，持久化在进程内存中，不变 |

---

## 39 张表全景图

按功能域分为 6 大模块：

### 模块一：对话核心（5张表）

| 表 | 行数 | 说明 |
|----|------|------|
| `chat_session` | 242 | 会话列表（标题、类型、时间） |
| `chat_turn` | 1,561 | 对话轮次（含 context JSON，token_usage 在这里） |
| `chat_message` | 3,116 | 消息元数据 |
| `chat_message_general` | 1,561 | 通用消息内容 |
| `chat_message_task` | 1,560 | 任务相关消息 |

**`chat_turn` 是最核心的表。** 每条记录代表一轮对话，`context` 字段是一个巨大的 JSON，包含：

```json
{
  "token_usage": {
    "prompt_tokens": 15012,
    "completion_tokens": 312,
    "total_tokens": 15324,
    "reasoning_tokens": 0,
    "cache_read_input_tokens": 12000,
    "cache_creation_input_tokens": 0
  },
  "persist_user_message_context": {
    "model_info": { "config_name": "kimi-k2.5" }
  },
  "trace_id": "86635a3441b4cc9a0779eb8fc3662bc3",
  "references": [...],
  "render_context": {...}
}
```

### 模块二：完整历史（1张表）

| 表 | 行数 | 说明 |
|----|------|------|
| `history_v2` | 18,310 | **完整对话内容**（raw_messages JSON） |

这是数据量最大的单表。每条记录包含完整的 `raw_messages` 数组（user/assistant/tool 所有消息），以及 `token_usage`、`agent_type`、`content_source` 等字段。

**按 agent_type + content_source 的分布：**

| agent_type | source | 条数 | tokens |
|-----------|--------|------|--------|
| solo_coder | RunCommand | 3,000 | 3,292,121 |
| solo_coder | user_input | 1,235 | 801,647 |
| solo_coder | llm_default | 1,039 | 535,584 |
| solo_coder | Read | 993 | 3,362,972 |
| solo_coder | TodoWrite | 884 | 550,983 |
| solo_coder | SearchReplace | 552 | 548,711 |
| solo_coder | Write | 536 | 1,926,767 |
| solo_agent | RunCommand | 917 | 294,239 |
| custom_v3 | RunCommand | 336 | 407,149 |
| ... | ... | ... | ... |

**关键发现：** `solo_coder` 占据了绝对主导地位（约 80% 的记录）。`RunCommand` 和 `Read` 是最频繁的工具调用，合计超过 4000 条。

**token_usage 分布：**

| 范围 | 条数 | tokens |
|------|------|--------|
| 1000-4999 | 3,419 | 7,543,590 |
| 10000+ | 403 | 7,231,278 |
| 5000-9999 | 988 | 6,742,322 |
| 500-999 | 4,408 | 3,094,199 |
| 100-499 | 8,434 | 2,614,252 |
| 1-99 | 656 | 54,101 |

超过 40% 的记录 token_usage 在 1000 以上，说明 Trae 的对话上下文普遍较长。

### 模块三：Agent 系统（4张表）

| 表 | 行数 | 说明 |
|----|------|------|
| `agent` | 17 | Agent 定义（含 system prompt、工具列表） |
| `agent_run` | 1,757 | Agent 运行记录 |
| `agent_member_relation` | 28 | Agent 成员关系 |
| `mcp_server_agent_relation` | 58 | MCP 服务器-Agent 关联 |

#### 17 个 Agent 完整列表

**3 个内置 Agent：**

| Agent | 说明 |
|-------|------|
| `solo_coder` | 主力模式，解决复杂编程问题，工具：readonly/edit/terminal/preview/web_search |
| `solo_agent` | 轻量模式 |
| `builder_v3` | 端到端开发（仅 1 条记录，几乎未使用） |

**14 个自定义 Agent：**

| Agent | 用途 |
|-------|------|
| UI Designer | UI/UX 设计 |
| Frontend Architect | 前端开发（React/Vue/Angular） |
| Backend Architect | 后端架构（API/数据库） |
| DevOps Architect | CI/CD、云基础设施 |
| Performance Expert | 性能分析与优化 |
| API Test Pro | API 测试 |
| Compliance Checker | 法律合规审查 |
| AI Integration Engineer | AI/ML 功能集成 |
| Prompt Architect | 模糊提示词重构 |
| GitHub MCP 代理 | GitHub 操作子 Agent |
| android-mcp-agent | Android UI 自动化 |
| mobile-mcp-agent | 移动端自动化 |
| playwright-mcp-agent | 浏览器自动化 |
| filesystem-mcp-agent | 文件系统操作 |
| git-mcp-agent | Git 操作 |
| database-analyst | 数据库分析 |
| 知识图谱管理器 | Memory MCP 知识图谱管理 |

所有自定义 Agent 都配置了 `readonly/edit/terminal/web_search` 基础工具。其中 `Prompt Architect` 额外拥有 `preview` 工具。

#### 16 个 MCP 服务器

| MCP 服务器 | 关联 Agent 数 | 类型 |
|-----------|-------------|------|
| Sequential Thinking | 10 | whitelist |
| Memory | 9 | whitelist |
| context7 | 5 | whitelist |
| android-mcp | 3 | whitelist |
| everything-search | 3 | whitelist |
| filesystem | 3 | **blacklist** |
| git | 3 | **blacklist** |
| github | 3 | **blacklist** |
| mobile-mcp | 3 | whitelist |
| playwright | 3 | **blacklist** |
| universal-db | 3 | whitelist |
| Playwright (alt) | 2 | whitelist |
| fetch | 2 | **blacklist** |
| playwright-executeautomation | 2 | whitelist |
| playwright-lite | 2 | whitelist |
| playwright-microsoft | 2 | whitelist |

**关键发现：** Sequential Thinking 和 Memory 是最通用的 MCP，被几乎所有 Agent 引用。filesystem/git/github/playwright 使用 **blacklist** 模式（默认全部可用，仅禁用指定工具），而其他 MCP 使用 **whitelist** 模式（仅启用指定工具）。

### 模块四：任务与待办（4张表）

| 表 | 行数 | 说明 |
|----|------|------|
| `task` | 1,455 | 任务记录 |
| `todo_list` | 1,812 | 待办事项（JSON 格式） |
| `history_todo_list` | 1,812 | 历史待办 |
| `session_project` | 242 | 会话-项目关联 |

**任务状态分布（task 表）：**

| 状态 | 数量 |
|------|------|
| completed | 1,106 |
| created | 346 |
| none | 3 |

**待办状态分布（todo_list 表，8771 条）：**

| 状态 | 数量 |
|------|------|
| completed | 4,130 |
| pending | 3,100 |
| in_progress | 1,541 |

完成率约 47%，有约 3100 条待办仍处于 pending 状态。

### 模块五：服务器端历史（1张表）

| 表 | 行数 | 说明 |
|----|------|------|
| `server_history_info` | 37,406 | 服务端完整历史（含 messages、token_usage、item_token_usage） |

这是 Trae 服务端视角的完整记录，比 `history_v2` 大近一倍。

**token 统计（服务端视角）：**

| 指标 | 数值 |
|------|------|
| token_usage 总和 | **1,190,861,228**（约 11.9 亿） |
| item_token_usage 总和 | 27,278,820 |
| 总记录数 | 37,406 |

**按 agent_type 分布：**

| agent_type | 条数 | token_usage | item_token |
|-----------|------|------------|-----------|
| solo_coder | 22,278 | 847,674,893 | 16,586,251 |
| solo_agent | 3,823 | 181,385,407 | 965,220 |
| custom_v3 | 4,405 | 85,633,449 | 3,956,585 |
| search_agent | 2,867 | 38,061,245 | 2,349,109 |
| browser_use_agent | 951 | 15,890,466 | 268,283 |
| general_purpose_agent | 1,075 | 12,506,673 | 1,228,582 |
| code_reviewer | 1,001 | 4,938,565 | 799,225 |
| code_review_summary | 670 | 2,333,258 | 836,076 |
| refactor_* | 335 | 2,437,312 | 289,202 |
| builder_v3 | 1 | 0 | 287 |

**关键发现：** 服务端 token_usage（11.9 亿）远大于客户端 chat_turn 统计的 1.08 亿。差异约 10 倍，可能原因：
1. 服务端统计包含了每次工具调用的完整上下文（而 chat_turn 只统计最终轮次）
2. 包含了被压缩/截断的历史对话
3. 包含了 internal reasoning tokens

### 模块六：配置与缓存（8张表）

| 表 | 行数 | 说明 |
|----|------|------|
| `user_configuration` | 2 | 用户功能开关 |
| `model_config_cache` | 42 | 模型配置缓存（21 种功能 × 2 个用户） |
| `rules_attachment` | 744 | 规则文件引用 |
| `project` | 25 | 项目信息 |
| `multi_root_path` | 16 | 多根路径配置 |
| `session_project` | 242 | 会话-项目关联 |
| `seaql_migrations` | 70 | 数据库迁移记录 |
| `migration_sql_store` | 70 | 迁移 SQL 存储 |

#### 用户功能配置

**已启用（16 项）：**
- `shallow_memento` — 浅层记忆
- `todo_list` — 待办列表（含 solo_enabled）
- `lint_error_autofix` — 自动修复 lint 错误
- `resource_diagnosis` — 资源诊断
- `stuck_chat_diagnosis` — 卡住对话诊断
- `ask_user_question` — 向用户提问
- `init_command` — 初始化命令
- `slash_commands` — 斜杠命令
- `chat_memory` — 对话记忆（含 with_history_enabled）
- `chat_input_completion` — 输入补全
- `chat_suggest` — 对话建议
- `past_chats` — 历史对话
- `fork_chat` — 分叉对话
- `visual_editor` — 可视化编辑器
- `deep_wiki` — 深度 Wiki
- `file_op_outside_workspace` — 工作区外文件操作

**已禁用（3 项）：**
- `knowledges` — 知识库
- `solo_team` — SOLO 团队模式
- `prevent_sleep` — 防止休眠

#### 模型配置缓存（21 种功能）

`model_config_cache` 存储了每种功能的模型请求配置。21 种功能包括：

`builder`, `builder_v3`, `chat`, `chat_v3`, `code_review_summary`, `code_reviewer`, `custom_agent_generation`, `git_ai`, `inline_chat`, `multimodal`, `refactor`, `solo_agent`, `solo_agent_lite`, `solo_agent_remote`, `solo_builder`, `solo_coder`, `solo_work_lite`, `solo_work_remote`, `system_diagnosis`, `ui_builder_v2`, `utils`

每种功能的 `config_data` 包含 `request_at`、`request_pin`、`data` 三个字段（字节数组编码），可能用于模型 API 的请求签名或路由。

#### 规则文件引用（rules_attachment）

**被引用最多的 AGENTS.md：**

| 文件 | 引用次数 |
|------|---------|
| `remote_gateway/AGENTS.md` | 236 |
| `openclaw/AGENTS.md` | 230 |
| `trae-unlock/AGENTS.md` | 81 |
| `api_key_test/AGENTS.md` | 58 |
| `trae-solo-unlock/AGENTS.md` | 50 |
| `jason-skill-hub/AGENTS.md` | 20 |

`remote_gateway` 和 `openclaw` 是最核心的项目，合计 466 次引用。

---

## 会话类型分析

**chat_session 的 242 个会话按类型分布：**

| 类型 | 数量 | 说明 |
|------|------|------|
| side_chat | 108 | 侧边栏对话 |
| inline_chat | 108 | 内联对话 |
| background_chat | 20 | 后台对话 |
| proactive_chat | 6 | 主动对话 |

**最近 20 个会话标题（降序）：**

| 时间 | 类型 | 标题 |
|------|------|------|
| 05-18 02:00 | side_chat | 重复运行 sleep 1 命令 |
| 05-17 03:46 | side_chat | 获取 Spec Mode 系统指令 |
| 05-17 03:21 | side_chat | 导出Sub Agent指令为Markdown |
| 05-17 01:11 | background_chat | 开始 |
| 05-12 21:03 | side_chat | 你好 |
| 05-10 19:25 | side_chat | 更新 Gitignore |
| 05-10 18:54 | inline_chat | Review Code Changes |
| 05-10 18:39 | inline_chat | Review Code Changes |
| 05-10 18:34 | inline_chat | Review Code Changes |
| 05-10 18:02 | inline_chat | Review Code Changes |
| 05-10 17:33 | inline_chat | Review Code Changes |
| 05-10 16:07 | inline_chat | Review Code Changes |

可以看到 5 月 10 日有大量 `Review Code Changes` 内联对话，说明那天在做代码审查。5 月 17 日在做 Spec Mode 和 Sub Agent 相关的研究工作。

---

## 数据关系图

```
chat_session (242)
  └─ session_project (242) ──► project (25)
  └─ chat_turn (1,561)
       ├─ context JSON ──► token_usage + model_info
       └─ agent_run_id ──► agent_run (1,757) ──► agent (17)
            └─ mcp_server_agent_relation (58) ──► 16 MCP servers

history_v2 (18,310)  ← 完整对话内容（raw_messages）
  └─ session_id ──► chat_session
  └─ agent_run_id ──► agent_run

server_history_info (37,406)  ← 服务端视角
  └─ session_id ──► chat_session
  └─ agent_run_id ──► agent_run

todo_list (1,812) ──► session_id ──► chat_session
task (1,455) ──► session_id ──► chat_session
rules_attachment (744) ──► chat_session_id ──► chat_session
```

---

## 一些有趣的发现

### 1. 两套 token 统计体系

数据库中存在**两套独立的 token 统计**：

| 来源 | 统计口径 | 总量 |
|------|---------|------|
| `chat_turn.context.token_usage` | 客户端，每轮对话 | **1.08 亿** |
| `server_history_info.token_usage` | 服务端，每次记录 | **11.9 亿** |

差异约 10 倍。服务端统计更大，可能因为它记录了每次工具调用的完整上下文开销，而客户端只统计最终轮次的净 token。

### 2. solo_coder 的绝对统治

在所有表中，`solo_coder` 都是绝对主力：

| 指标 | solo_coder 占比 |
|------|----------------|
| history_v2 记录数 | ~80% |
| server_history_info token_usage | ~71% |
| agent_run 记录数 | ~85% |
| chat_turn 记录数 | ~75% |

### 3. 14 个自定义 Agent 但只用了一小部分

虽然创建了 14 个自定义 Agent，但实际有使用记录的只有：
- `custom_v3`（4405 条 server_history_info 记录）
- `code_reviewer`（1001 条）
- `code_review_summary`（670 条）
- `refactor_finder/planner/scoper/incrementer`（335 条）
- `browser_use_agent`（951 条）
- `general_purpose_agent`（1075 条）
- `search_agent`（2867 条）

像 `UI Designer`、`Frontend Architect`、`Backend Architect`、`DevOps Architect` 等 Agent 在 server_history_info 中**完全没有记录**，说明它们被定义了但从未被实际调用。

### 4. MCP 使用的两种模式

16 个 MCP 服务器中：
- **whitelist 模式（11 个）**：仅启用指定工具，更安全
- **blacklist 模式（5 个）**：默认全部可用，仅禁用指定工具

filesystem、git、github、playwright 使用 blacklist 模式，说明这些是"信任度高"的基础工具。而 Sequential Thinking、Memory、context7 等使用 whitelist 模式。

### 5. 数据库迁移历史

`seaql_migrations` 和 `migration_sql_store` 各有 70 行，说明这个数据库 schema 经历了 70 次迁移。从最初的简单结构逐步演化到现在的 39 张表。

---

## 未解之谜

1. **`model_config_cache.config_data`** — 字节数组编码，无法直接解码。可能包含模型 API 的请求签名密钥或路由参数
2. **`server_history_info` 与 `history_v2` 的 10 倍 token 差异** — 需要进一步分析 messages 字段的内容差异
3. **`agent_run` 只有元数据** — 没有 token 使用量、没有运行结果，只有 agent_id 和时间戳
4. **`compress_token_usage` 字段** — 在 history_v2 中存在但全部为 NULL，可能是预留的压缩统计字段

---

## 总结

Trae IDE 的数据库是一个设计精巧的多层存储体系：

- **会话层**：`chat_session` + `chat_turn` 记录对话轮次和 token
- **历史层**：`history_v2` 存储完整对话内容（18310 条）
- **服务层**：`server_history_info` 记录服务端视角的完整历史（37406 条）
- **Agent 层**：`agent` + `agent_run` + `mcp_server_agent_relation` 管理 Agent 和 MCP
- **任务层**：`task` + `todo_list` 管理待办和任务
- **配置层**：`user_configuration` + `model_config_cache` + `rules_attachment`

39 张表、17 个 Agent、16 个 MCP、8771 条待办、18310 条完整对话、11.9 亿服务端 tokens——这就是 Trae IDE 眼中的一个用户的全部画像。

---

**项目地址**：[trae-db-decrypt](https://github.com/bigmanBass666/trae-db-decrypt)

**依赖**：Python 3.10+，pycryptodome

**致谢**：核心解密方法受 [wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) 启发。
