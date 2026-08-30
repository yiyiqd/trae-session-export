# Trae CN Database Decryptor

> 🌐 [Oh My Trae](https://github.com/oh-my-trae/oh-my-trae) 生态导航
>
> | 🔓 解密 | 💾 记忆 | 🛠️ 解锁 | 🤖 Solo |
> |---------|---------|----------|---------|
> | **trae-db-decrypt** | [trae-to-claude-mem](https://github.com/oh-my-trae/trae-to-claude-mem) | [trae-unlock](https://github.com/oh-my-trae/trae-unlock) | [trae-solo-unlock](https://github.com/oh-my-trae/trae-solo-unlock) |

> Trae CN SQLCipher 4 数据库解密 + Token 使用量分析工具

## 功能

- 从进程内存中提取 SQLCipher 密钥（Windows API，无需 Frida）
- 纯 Python 页面级 SQLCipher 4 数据库解密（受 wechat-decrypt 启发）
- 导出完整的对话记录和 Agent 数据
- Token 使用量分析报告（按模型/项目/日期统计）
- HMAC-SHA512 自动验证密钥正确性

## 快速开始

### 1. 提取密钥（需要 Trae CN 正在运行）

```bash
pip install -r requirements.txt   # pycryptodome
python src/scan_memory.py
```

### 2. 解密数据库

```bash
python src/decrypt_db.py    # 使用默认路径，输出 database_decrypted.db
python src/decrypt_db.py -k decrypted_key.json -o output.db
```

### 3. 生成 Token 使用量报告

```bash
python src/token_report.py                         # 默认读取 database_decrypted.db
python src/token_report.py -d /path/to/decrypted.db
```

## 项目结构

```
trae-db-decrypt/
├── README.md
├── requirements.txt
├── src/
│   ├── scan_memory.py       # 密钥扫描脚本（从进程内存提取）
│   ├── decrypt_db.py        # 数据库解密工具（页面级 AES-CBC）
│   └── token_report.py      # Token 使用量分析报告
├── docs/
│   ├── article.md           # Trae CN 技术文章（解密教程 + 探索历程）
│   ├── article_solo.md      # Trae SOLO CN 技术文章
│   └── TRAEDB_GUIDE.md      # 数据库详细使用指南
└── examples/                # 示例代码
```

## 工作原理

1. **进程发现**：找到加载 `ai_agent.dll` 的 Trae CN 进程
2. **内存扫描**：用 Windows API 读取进程内存，搜索 hex 密钥模式
3. **密钥验证**：用 HMAC-SHA512 验证找到的密钥是否正确
4. **数据库解密**：纯 Python 逐页 AES-CBC 解密 SQLCipher 4 数据库
5. **数据分析**：从 `chat_turn.context` 提取 `token_usage` 和 `model_info`

## 数据库表结构（39 张表）

### 核心对话表

| 表名 | 说明 |
|------|------|
| `history_v2` | 完整聊天内容（JSON格式） |
| `chat_session` | 会话列表 |
| `chat_message` | 消息元数据 |
| `chat_turn` | 对话轮次，含 `context.token_usage` 和 `model_info` |

### Token 使用量关键字段

`chat_turn.context` JSON 中包含：

```json
{
  "token_usage": {
    "prompt_tokens": 15012,
    "completion_tokens": 312,
    "total_tokens": 15324,
    "reasoning_tokens": 0,
    "cache_read_input_tokens": 1536,
    "cache_creation_input_tokens": 0
  },
  "persist_user_message_context": {
    "model_info": { "config_name": "kimi-k2.5", ... }
  }
}
```

## 参考项目

- [wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) - 微信数据库解密项目（页面级解密方法的主要参考）

## 许可证

MIT License
