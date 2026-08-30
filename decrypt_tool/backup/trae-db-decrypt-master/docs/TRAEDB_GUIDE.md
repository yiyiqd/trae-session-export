# Trae CN database.db 使用指南

## 概述

这是 Trae CN IDE 的本地数据库文件，使用 SQLCipher 4 加密。包含所有 AI Agent 的对话记录、任务执行、项目配置等数据。

## 解密密钥

```
密钥: 3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773
格式: x'3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773' (raw key 模式)
数据库文件: database.db (约 420MB)
```

## 解密方法

### 方法1: SQLCipher CLI

```bash
sqlcipher database.db
PRAGMA key = "x'3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773'";
SELECT count(*) FROM sqlite_master;
```

### 方法2: 已导出的 JSON 文件（无需解密）

- `trae_full_data.json` - 223 个完整对话（含消息内容）
- `trae_complete_data.json` - 所有其他表格数据

## 数据库表结构

### 核心对话表

| 表名 | 行数 | 说明 |
|------|------|------|
| chat_session | 238 | 会话列表 |
| chat_message | 3048 | 消息元数据 |
| chat_turn | 1527 | 对话轮次 |
| **history_v2** | 15914 | **完整聊天内容（JSON格式）** |

### Agent 相关表

| 表名 | 行数 | 说明 |
|------|------|------|
| agent | 17 | Agent 定义（含 system prompt） |
| agent_run | 1689 | Agent 运行记录 |
| agent_member_relation | 28 | Agent 成员关系 |

### 任务/项目表

| 表名 | 行数 | 说明 |
|------|------|------|
| task | 1424 | 任务记录 |
| project | 23 | 项目信息 |
| todo_list | 1739 | 待办事项 |
| history_todo_list | 1739 | 历史待办 |

### 配置/缓存表

| 表名 | 行数 | 说明 |
|------|------|------|
| session_project | 238 | 会话-项目关联 |
| model_config_cache | 42 | 模型配置缓存 |
| mcp_server_agent_relation | 58 | MCP 服务器-Agent 关联 |
| rules_attachment | 744 | 规则附件 |
| server_history_info | 32692 | 服务器历史信息 |
| user_configuration | 2 | 用户配置 |
| multi_root_path | 15 | 多根路径配置 |

## 关键表详解

### 1. history_v2 (最重要的表)

这是存储**完整聊天内容**的表，包含 15,914 条记录。

**字段说明：**
- `id` (INTEGER): 主键
- `history_v2_id` (TEXT): 历史记录唯一ID
- `session_id` (TEXT): 关联的会话ID
- `message_id` (TEXT): 关联的消息ID
- `messages` (TEXT): **完整聊天内容（JSON格式）**
- `token_usage` (INTEGER): token 使用量
- `agent_type` (TEXT): Agent 类型
- `content_source` (TEXT): 内容来源
- `created_at` (bigint): 创建时间戳

**messages 字段格式 (JSON)：**
```json
{
  "raw_messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "用户消息内容"}
      ]
    },
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "AI 回复内容"}
      ]
    }
  ]
}
```

### 2. chat_session (会话表)

**字段说明：**
- `id` (INTEGER): 主键
- `session_id` (TEXT): 会话唯一ID
- `project_id` (TEXT): 关联的项目ID
- `session_title` (TEXT): 会话标题
- `session_type` (TEXT): 会话类型
- `created_at` (bigint): 创建时间戳
- `updated_at` (bigint): 更新时间戳

**session_type 类型：**
- `side_chat`: 侧边栏对话
- `background_chat`: 后台任务
- `inline_chat`: 内联对话（代码审查等）
- `proactive_chat`: 主动建议

### 3. agent (Agent 定义表)

**字段说明：**
- `id` (INTEGER): 主键
- `name` (TEXT): Agent 名称
- `description` (TEXT): 描述
- `system_prompt` (TEXT): 系统提示词
- `tools` (TEXT): 可用工具列表 (JSON)
- `agent_type` (TEXT): Agent 类型
- `created_at` (bigint): 创建时间戳

**tools 字段 (JSON)：**
```json
[{"value":"readonly"}, {"value":"edit"}, {"value":"terminal"}, {"value":"web_search"}]
```

### 4. agent_run (Agent 运行记录)

**字段说明：**
- `id` (INTEGER): 主键
- `session_id` (TEXT): 关联的会话ID
- `agent_type` (TEXT): Agent 类型
- `status` (TEXT): 运行状态
- `token_usage` (INTEGER): token 使用量
- `created_at` (bigint): 创建时间戳

### 5. task (任务表)

**字段说明：**
- `id` (INTEGER): 主键
- `task_id` (TEXT): 任务唯一ID
- `session_id` (TEXT): 关联的会话ID
- `message_id` (TEXT): 关联的消息ID
- `status` (TEXT): 任务状态
- `created_at` (bigint): 创建时间戳
- `updated_at` (bigint): 更新时间戳

## 常用查询示例

### 查询所有会话及其消息数量

```sql
SELECT 
    s.session_id,
    s.session_title,
    s.session_type,
    COUNT(DISTINCT h.id) as message_count,
    MAX(h.created_at) as last_activity
FROM chat_session s
LEFT JOIN history_v2 h ON s.session_id = h.session_id
GROUP BY s.session_id
ORDER BY last_activity DESC;
```

### 提取完整对话内容

```sql
SELECT 
    s.session_title,
    h.messages,
    h.agent_type,
    h.created_at
FROM history_v2 h
JOIN chat_session s ON h.session_id = s.session_id
WHERE h.messages IS NOT NULL
ORDER BY h.created_at DESC;
```

### 查询 Agent 定义和系统提示

```sql
SELECT 
    name,
    description,
    system_prompt,
    tools
FROM agent;
```

### 查询所有任务及其状态

```sql
SELECT 
    task_id,
    session_id,
    status,
    created_at,
    updated_at
FROM task
ORDER BY created_at DESC;
```

### 查询特定会话的所有消息

```sql
SELECT 
    h.messages,
    h.agent_type,
    h.token_usage,
    h.created_at
FROM history_v2 h
WHERE h.session_id = '你的session_id'
ORDER BY h.created_at ASC;
```

### 查询所有 Agent 运行记录

```sql
SELECT 
    run_id,
    session_id,
    agent_type,
    status,
    token_usage,
    created_at
FROM agent_run
ORDER BY created_at DESC
LIMIT 100;
```

### 提取 Agent 系统提示词

```sql
SELECT 
    name as agent_name,
    system_prompt
FROM agent
WHERE agent_type = 'custom';
```

## 数据统计

- **总会话数**: 238
- **总消息数**: 3048
- **完整对话记录**: 15914
- **Agent 数量**: 17
- **Agent 运行次数**: 1689
- **任务数量**: 1424
- **项目数量**: 23
- **待办事项**: 1739

## 文件位置

- **原始数据库**: `C:/Users/86150/AppData/Roaming/Trae CN/ModularData/ai-agent/database.db`
- **解密后副本**: `D:/Test/claude_test/subagent_test/database.db`
- **密钥文件**: `D:/Test/claude_test/subagent_test/decrypted_key.json`
- **导出数据**: `D:/Test/claude_test/subagent_test/trae_full_data.json`

## 注意事项

1. 数据库使用 SQLCipher 4 加密，需要支持 SQLCipher 的 SQLite 库才能读取
2. 密钥是 raw key 格式，不需要额外的 KDF 派生
3. 部分字段包含 JSON 格式数据，需要解析后使用
4. 时间戳字段使用 Unix 时间戳（秒）
