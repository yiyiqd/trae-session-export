# Trae Session Export

把 **Trae（TRAE SOLO CN / Trae CN）** 的会话导出为 Markdown：真正的**对话记录**（`## user` / `## assistant` 交替），支持双数据源切换、中文会话标题、一键导出全部会话。

> ⚠️ **仅供读取和管理自己电脑上的自己的数据**。请勿用于他人数据。

## 功能

- **对话记录导出**：user 原始输入 + assistant 完整回答（含中间过程），markdown 原文保真
- **双数据源**：Trae Work（TRAE SOLO CN）/ Trae CN，页面一键切换
- **中文会话标题**：来自解密数据库的 `chat_session.session_title`
- **一键导出所有**：全部会话打包 zip 下载
- **纯本地运行**：Flask 起在 127.0.0.1，数据不出本机

## 快速开始

```bash
pip install flask pycryptodome
python trae_web.py
# 浏览器打开 http://127.0.0.1:5001
```

1. 双击 `decrypt_tool/刷新密钥并解密.bat`（需要 Trae 正在运行，密钥在进程内存里）
2. 浏览器刷新页面，点「加载会话列表」即可看到中文标题
3. 选择会话「导出对话 MD」，或「一键导出所有」

详见 [README_Trae导出器.md](README_Trae导出器.md)。

## 目录结构

```
├─ trae_web.py            Web 导出器（Flask + 内嵌前端）
├─ trae_gitlib.py         纯 Python git 对象解析库（无 git 依赖）
├─ 启动Trae导出器.bat
└─ decrypt_tool/          数据库解密工具链
   ├─ scan_solo.py        进程内存扫描提取 SQLCipher 密钥（适配 TRAE SOLO CN）
   ├─ scan_memory.py      内存扫描原版
   ├─ decrypt_db.py       页面级 AES-256-CBC 解密
   ├─ 刷新密钥并解密.bat    一键：扫密钥 → 解密两个库
   └─ backup/             原工具备份与换电脑安装说明
```

## 工作原理

1. **密钥提取**：Trae 的会话数据库是 SQLCipher 4 加密（AES-256-CBC / PBKDF2-HMAC-SHA512 / 256000 迭代），密钥首次启动时随机生成、保存在进程内存中。`scan_solo.py` 用 `ReadProcessMemory` 扫描进程内存找到 `x'<64hex>'` 形式的密钥，并用数据库第一页的 HMAC-SHA512 校验正确性。
2. **页面级解密**：`decrypt_db.py` 逐页 AES 解密（每页 4096 字节，尾部 80 字节 reserve = IV + HMAC），还原出明文 SQLite。
3. **对话重建**：user 输入取 `chat_message_general`（干净原文），assistant 回答按 `server_history_info` 增量流重组（本地 `history_v2` 会被微压缩丢正文），再拼接每轮的最终回答（`chat_message_task` 的 summary）。

## 致谢

- 内存扫描与解密方法来自 [Oh-My-Trae/trae-db-decrypt](https://github.com/Oh-My-Trae/trae-db-decrypt)（backup/ 目录为其源码备份），灵感来自 [wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)。

## License

仅供学习与个人数据管理使用。请遵守当地法律法规与软件服务条款。
