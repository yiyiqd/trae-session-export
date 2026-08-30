# Trae 对话记录导出器（Web 版）

同时支持 **Trae Work（TRAE SOLO CN）** 和 **Trae CN（普通版）** 两个数据源，从解密数据库导出**真正的对话记录**（`## user` / `## assistant` 交替，含全部对话文本），列表显示中文会话标题。

## 启动

双击 `启动Trae导出器.bat`，或：

```bash
cd /d "F:\Ai\Session export\Trae Session export"
python trae_web.py
```

浏览器打开 **http://127.0.0.1:5001**。

## 使用

**切换数据源**：页面顶部的三个按钮 —— `Trae Work（SOLO）` / `Trae CN` / `全部`（"全部"仅用于一键导出，两个数据源一起打包）。

**单个导出**
1. 选中数据源后点击 **加载会话列表** —— 显示中文标题 + 提交数 + 最后时间，点列表项填入 ID
2. 或直接粘贴 Trae 会话 ID（20 位十六进制，如 `6a806fbd779c243e6fadb21b`）
3. 点击 **查询会话信息** 确认，再点 **导出 MD 文件** 下载

**批量导出**
- **一键导出所有** —— 把当前数据源全部会话的 MD（文件名带中文标题）打包成 zip 下载；数据源选"全部"时一起导出

## 获取中文标题（解密数据库，可选）

中文标题和完整对话存在加密的 `database.db` 里。要显示中文标题，需先解密一次：

1. 确保 **TRAE SOLO CN 或 Trae CN 至少一个正在运行**（密钥在进程内存里）
2. 双击 `decrypt_tool\刷新密钥并解密.bat`
   - 扫描进程内存提取 SQLCipher 密钥（`scan_solo.py`）
   - 解密 TRAE SOLO CN 数据库 → `database_decrypted.db`
   - 解密 Trae CN 数据库 → `database_traecn_decrypted.db`
   - **两个程序的加密机制相同，本机密钥通用**（实测 SOLO 密钥直接解开 Trae CN 库）
3. 回到浏览器 Ctrl+F5 刷新，两个数据源的列表即显示中文标题

密钥提取方法参考 [Oh-My-Trae/trae-db-decrypt](https://github.com/Oh-My-Trae/trae-db-decrypt)：
SQLCipher 4（AES-256-CBC、PBKDF2-HMAC-SHA512、256000 迭代），密钥以 `x'<64hex>'` 形式存于运行进程内存，用 HMAC-SHA512 校验。

## 输出

- 导出文件保存在 `F:\Ai\Session export\Trae Session export\`，文件名 `trae_session_<标题>_<id前8位>.md`
- 内容：**完整对话记录**——`## user` / `## assistant` 交替，user 为原始输入，assistant 含中间过程与最终回答
- 一键导出所有：全部会话的对话 MD 打包 zip（数据源选"全部"时两个库一起导）

## 数据原理

| 数据 | Trae Work（SOLO） | Trae CN |
|------|------------------|---------|
| 加密数据库 | `%APPDATA%\TRAE SOLO CN\...ai-agent\database.db` | `%APPDATA%\Trae CN\...ai-agent\database.db` |
| 解密后 | `decrypt_tool\database_decrypted.db` | `decrypt_tool\database_traecn_decrypted.db` |

两版本表结构相同，导出时取：
- 会话与中文标题：`chat_session`
- 用户输入：`chat_message_general.content`（干净原文）
- assistant 回答：`history_v2.messages` 的 raw_messages（role=assistant 的 text 段拼接；缺失时用 task 的 thought/reasoning 兜底）

## 说明

- 解密库是运行 bat 时的快照，之后新产生的对话要重新运行 `decrypt_tool\刷新密钥并解密.bat` 才能看到。
- 极少数纯工具轮次（无回答文本）在 MD 中显示"（无记录）"。
- 会话 ID 是 20 位十六进制（不是 `sess_` 格式）。

## 技术备注

- 纯 Python 解析 git 对象（zlib），无需安装 git
- 解密依赖 `pycryptodome`（`pip install pycryptodome`）
