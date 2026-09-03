# -*- coding: utf-8 -*-
"""
Trae Session 对话记录导出器（Web 版）
从解密数据库导出 Trae 的真正对话记录（user / assistant 交替），支持双数据源：
  - Trae Work（TRAE SOLO CN）
  - Trae CN（普通版）
两者加密机制相同，本机 SQLCipher 密钥通用（见 decrypt_tool）。

用法：python trae_web.py  然后打开 http://127.0.0.1:5001
前提：先双击 decrypt_tool\\刷新密钥并解密.bat 生成解密数据库。
"""
import os
import re
import io
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, send_file

# ---------- 路径配置 ----------
EXPORT_DIR = Path(__file__).resolve().parent / "export"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DECRYPT_TOOL = Path(__file__).resolve().parent / "decrypt_tool"
SOURCES = {
    "solo": {
        "label": "Trae Work（SOLO）",
        "decrypted_db": DECRYPT_TOOL / "database_decrypted.db",
        "prefix": "trae_session",
    },
    "cn": {
        "label": "Trae CN",
        "decrypted_db": DECRYPT_TOOL / "database_traecn_decrypted.db",
        "prefix": "traecn_session",
    },
}

SESSION_ID_RE = re.compile(r"^[0-9a-f]{20,24}$")

app = Flask(__name__)


def format_ts(ts):
    """秒级时间戳 -> 可读时间"""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts or "")


def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (name or "").strip())
    return name or "session"


# ---------- 数据库访问 ----------
def open_db(source):
    """打开解密数据库；不存在返回 None。"""
    db_path = SOURCES[source]["decrypted_db"]
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    return conn


def db_sessions(source):
    """从解密库列出全部会话 [{id, title, created, updated, turns}]"""
    conn = open_db(source)
    if conn is None:
        return None
    try:
        rows = conn.execute(
            "SELECT session_id, session_title, created_at, updated_at FROM chat_session "
            "ORDER BY ifnull(updated_at, created_at) DESC"
        ).fetchall()
        turns = dict(conn.execute(
            "SELECT session_id, count(*) FROM chat_message "
            "WHERE message_role='user' AND ifnull(deleted_at,0)=0 GROUP BY session_id"
        ).fetchall())
        out = []
        for sid, title, created, updated in rows:
            out.append({
                "id": sid,
                "title": (title or "").strip(),
                "created": format_ts(created),
                "updated": format_ts(updated),
                "turns": turns.get(sid, 0),
            })
        return out
    finally:
        conn.close()


# ---------- 对话解析 ----------
def _general_text(raw):
    """chat_message_general.content -> 用户输入文本"""
    if not raw:
        return ""
    try:
        arr = json.loads(raw)
        parts = []
        for p in (arr if isinstance(arr, list) else []):
            if isinstance(p, dict):
                t = p.get("text_content") or p.get("text") or ""
                if t:
                    parts.append(t)
        return "\n".join(parts).strip()
    except Exception:
        return str(raw).strip()


def _assistant_text(raw):
    """history_v2.messages -> assistant 过程文本（多段 text 按顺序拼接）"""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        parts = []
        for m in data.get("raw_messages", []):
            if m.get("role") != "assistant":
                continue
            c = m.get("content")
            if isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text":
                        t = (p.get("text") or "").strip()
                        if t:
                            parts.append(t)
            elif isinstance(c, str) and c.strip():
                parts.append(c.strip())
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def _task_summary(task_raw):
    """chat_message_task.content -> plan_item.tool_call_info.params.summary（该轮最终完整回答）"""
    if not task_raw:
        return ""
    try:
        data = json.loads(task_raw)
        parts = []
        for m in data.get("messages", []):
            pi = m.get("plan_item") or {}
            ti = pi.get("tool_call_info") or {}
            params = ti.get("params") or {}
            s = params.get("summary")
            if isinstance(s, str) and s.strip():
                parts.append(s.strip())
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def _task_tool_blocks(task_raw):
    """chat_message_task.content -> 该轮全部工具调用的渲染块（Write/Edit 代码、RunCommand 命令等）。"""
    if not task_raw:
        return []
    blocks = []
    try:
        data = json.loads(task_raw)
    except Exception:
        return []
    for m in data.get("messages", []):
        pi = m.get("plan_item") or {}
        ti = pi.get("tool_call_info") or {}
        name = ti.get("name") or ""
        if not name or name in ("finish", "CompactFake"):
            continue
        params = ti.get("params") or {}
        # 跳过空操作（如 old/new 均为空的 Edit）
        if name == "Edit" and not params.get("old_string") and not params.get("new_string") and not params.get("content"):
            continue
        block = _render_trae_tool(name, params)
        if block:
            blocks.append(block)
    return blocks


def _assistant_full(history_rows, task_raw):
    """组合 assistant 全文：过程文本（history_v2）+ 最终回答（task summary）"""
    parts = []
    for raw in history_rows:
        t = _assistant_text(raw)
        if t:
            parts.append(t)
    summary = _task_summary(task_raw)
    # 去重：summary 若已被过程文本包含则不重复
    joined = "\n\n".join(parts)
    if summary and summary not in joined:
        parts.append(summary)
    return "\n\n".join(parts).strip()


def _render_trae_tool(name, params):
    """把 Trae 一次工具调用渲染成 markdown（input 全保，防超大）。"""
    params = params or {}

    def code_block(s, lang=""):
        s = str(s)
        return f"```{lang}\n{s}\n```"

    lines = [f"🔧 **[{name}]**"]
    body = []
    if name == "Write":
        body.append(f"创建文件：`{params.get('file_path', '')}`")
        body.append(code_block(params.get("content", "")))
    elif name == "Edit":
        body.append(f"编辑文件：`{params.get('file_path', '')}`")
        if params.get("old_string"):
            body.append("旧内容：\n" + code_block(params["old_string"]))
        if params.get("new_string"):
            body.append("新内容：\n" + code_block(params["new_string"]))
    elif name in ("RunCommand", "CheckCommandStatus", "StopCommand"):
        if params.get("command"):
            body.append(code_block(params["command"], "bash"))
    elif name == "Read":
        body.append(f"读取文件：`{params.get('file_path', '')}`")
    elif name == "Grep":
        body.append(f"搜索 `{params.get('path', '')}`：{params.get('pattern', '')}")
    elif name == "LS":
        body.append(f"列目录：`{params.get('path', '')}`")
    elif name == "Glob":
        body.append(f"匹配 `{params.get('path', '')}`：{params.get('pattern', '')}")
    elif name == "DeleteFile":
        body.append(f"删除文件：{params.get('file_paths')}")
    elif name == "TodoWrite":
        for t in params.get("todos") or []:
            if isinstance(t, dict):
                body.append(f"- [{t.get('status', '')}] {t.get('content', '')}")
            else:
                body.append(f"- {t}")
    elif name == "WebSearch":
        body.append(f"搜索：{params.get('query', '')}")
    elif name == "AskUserQuestion":
        for q in params.get("questions") or []:
            if isinstance(q, dict):
                body.append(f"提问：{q.get('question', '')}")
            else:
                body.append(f"提问：{q}")
    elif name == "finish":
        return ""  # finish.summary 在对话文本里已有，不重复
    else:
        try:
            s = json.dumps(params, ensure_ascii=False)
        except Exception:
            s = str(params)
        if len(s) > 1500:
            s = s[:1500] + " ...(截断)"
        body.append(code_block(s, "json"))

    return "\n".join(lines + body).strip()


def _server_stream_groups(conn, sid):
    """从 server_history_info 增量流重建：以 user 行为界分组 assistant 文本。
    工具调用（Write/Edit/RunCommand 等的代码与命令）在 plan_item 结构的行里一并收集。
    返回 [[assistant_text, ...], ...] 或 None。"""
    groups = []
    try:
        srows = conn.execute(
            "SELECT messages FROM server_history_info WHERE conversation_id=? "
            "ORDER BY created_at, rowid", (sid,)
        ).fetchall()
    except Exception:
        return None
    if not srows:
        return None
    for (raw,) in srows:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for m in data.get("raw_messages", []):
            role = m.get("role")
            if role == "user":
                groups.append([])
                continue
            if role != "assistant":
                continue
            if not groups:
                groups.append([])
            c = m.get("content")
            texts = []
            if isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text":
                        t = (p.get("text") or "").strip()
                        if t:
                            texts.append(t)
            elif isinstance(c, str) and c.strip():
                texts.append(c.strip())
            # 工具调用：raw_messages[].tool_calls[].function_call（name + arguments JSON 串）
            for tc in (m.get("tool_calls") or []):
                fc = (tc or {}).get("function_call") or {}
                name = fc.get("name") or "?"
                try:
                    params = json.loads(fc.get("arguments") or "{}")
                except Exception:
                    params = {"raw": (fc.get("arguments") or "")[:500]}
                block = _render_trae_tool(name, params)
                if block:
                    texts.append(block)
            for t in texts:
                if not groups[-1] or groups[-1][-1] != t:
                    groups[-1].append(t)
    return groups or None


def fetch_conversation(conn, sid):
    """取一个会话的完整对话，返回 [{role, text}]。
    user 取 chat_message_general（干净原文）；
    assistant 优先用 server_history_info 增量流重组（每轮过程+最终回答），
    server 不可用时回退 history_v2 + task summary。"""
    rows = conn.execute(
        "SELECT message_id, message_role FROM chat_message "
        "WHERE session_id=? AND ifnull(deleted_at,0)=0 ORDER BY message_index",
        (sid,),
    ).fetchall()
    asst_mids = [mid for mid, role in rows if role == "assistant"]

    # task：每轮最终回答 summary + 工具调用块（Write/Edit 代码、RunCommand 命令等）
    summaries = []
    tool_blocks_list = []
    for mid in asst_mids:
        r = conn.execute(
            "SELECT content FROM chat_message_task WHERE message_id=?", (mid,)
        ).fetchone()
        raw = r[0] if r else ""
        summaries.append(_task_summary(raw))
        tool_blocks_list.append(_task_tool_blocks(raw))

    # server 流分组
    groups = _server_stream_groups(conn, sid)
    if groups is not None and len(groups) == len(asst_mids):
        asst_texts = ["\n\n".join(g) for g in groups]
    else:
        asst_texts = None  # 回退

    turns = []
    asst_i = 0
    for mid, role in rows:
        if role == "user":
            r = conn.execute(
                "SELECT content FROM chat_message_general WHERE message_id=?", (mid,)
            ).fetchone()
            text = _general_text(r[0] if r else "")
        else:
            i = asst_i
            asst_i += 1
            if asst_texts is not None:
                pieces = [x for x in [asst_texts[i]] + tool_blocks_list[i] if x]
                s = summaries[i]
                if s and s not in asst_texts[i]:
                    pieces.append(s)
                text = "\n\n".join(pieces).strip()
            else:
                h_rows = [r[0] for r in conn.execute(
                    "SELECT messages FROM history_v2 WHERE message_id=? AND ifnull(deleted_at,0)=0 ORDER BY id",
                    (mid,),
                ).fetchall()]
                pieces = [x for x in [_assistant_full(h_rows, None)] + tool_blocks_list[i] if x]
                s = summaries[i]
                if s and s not in pieces:
                    pieces.append(s)
                text = "\n\n".join(pieces).strip()
        turns.append({"role": role, "text": text})
    return turns


# ---------- MD 生成 ----------
def build_chat_md(session_id, source):
    """生成对话记录 MD，返回 (md_text, meta) 或 (None, error)"""
    conn = open_db(source)
    if conn is None:
        return None, ("未找到解密数据库：{}\n请先双击 decrypt_tool\\刷新密钥并解密.bat"
                      .format(SOURCES[source]["decrypted_db"]))
    try:
        row = conn.execute(
            "SELECT session_title, created_at, updated_at FROM chat_session WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return None, f"会话 {session_id} 不在当前数据源中"
        title, created, updated = row
        turns = fetch_conversation(conn, session_id)
    finally:
        conn.close()

    label = SOURCES[source]["label"]
    display = title.strip() or session_id
    user_turns = sum(1 for t in turns if t["role"] == "user")

    L = []
    L.append(f"# {display}")
    L.append("")
    L.append(f"> 来源: {label}  |  Session: `{session_id}`")
    L.append(f"> 创建: {format_ts(created)}  |  更新: {format_ts(updated)}  |  轮数: {user_turns}")
    L.append("")
    L.append("---")
    L.append("")

    empty_user = 0
    empty_asst = 0
    for t in turns:
        role_name = "user" if t["role"] == "user" else "assistant"
        if role_name == "user" and not t["text"]:
            empty_user += 1
        if role_name == "assistant" and not t["text"]:
            empty_asst += 1
        L.append(f"## {role_name}")
        L.append("")
        L.append(t["text"] if t["text"] else "（无记录）")
        L.append("")
        L.append("---")
        L.append("")

    meta = {
        "title": display,
        "turns": user_turns,
        "messages": len(turns),
        "empty_user": empty_user,
        "empty_assistant": empty_asst,
        "chars": sum(len(t["text"]) for t in turns),
    }
    return "\n".join(L), meta


# ---------- API ----------
def get_source():
    s = (request.args.get("source") or (request.get_json(silent=True) or {}).get("source") or "solo")
    s = str(s).strip().lower()
    return s if s in SOURCES else "solo"


@app.route("/")
def index():
    return HTML_PAGE


@app.get("/api/sessions")
def api_sessions():
    source = get_source()
    sessions = db_sessions(source)
    if sessions is None:
        return jsonify({"ok": False,
                        "error": f"未找到解密数据库（{SOURCES[source]['decrypted_db']}）。请先双击 decrypt_tool\\刷新密钥并解密.bat"})
    return jsonify({"ok": True, "source": source, "count": len(sessions), "sessions": sessions})


@app.post("/api/info")
def api_info():
    data = request.get_json(silent=True) or {}
    source = get_source()
    sid = (data.get("session_id") or "").strip().lower()
    if not SESSION_ID_RE.match(sid):
        return jsonify({"ok": False, "error": "会话 ID 格式不正确，应为 20~24 位十六进制"})
    conn = open_db(source)
    if conn is None:
        return jsonify({"ok": False, "error": "未找到解密数据库，请先运行 decrypt_tool\\刷新密钥并解密.bat"})
    try:
        row = conn.execute(
            "SELECT session_title, created_at, updated_at FROM chat_session WHERE session_id=?",
            (sid,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"会话不在 {SOURCES[source]['label']} 数据源中"})
        title = (row[0] or "").strip()
        turns = fetch_conversation(conn, sid)
        user_turns = sum(1 for t in turns if t["role"] == "user")
        return jsonify({
            "ok": True, "session_id": sid, "title": title or sid,
            "source": SOURCES[source]["label"],
            "turns": user_turns, "messages": len(turns),
            "created": format_ts(row[1]), "updated": format_ts(row[2]),
        })
    finally:
        conn.close()


@app.post("/api/export")
def api_export():
    data = request.get_json(silent=True) or {}
    source = get_source()
    sid = (data.get("session_id") or "").strip().lower()
    if not SESSION_ID_RE.match(sid):
        return jsonify({"ok": False, "error": "会话 ID 格式不正确，应为 20~24 位十六进制"})

    md_text, meta = build_chat_md(sid, source)
    if md_text is None:
        return jsonify({"ok": False, "error": meta})

    prefix = SOURCES[source]["prefix"]
    fname = f"{prefix}_{safe_filename(meta['title'])}_{sid[:8]}.md"
    out_path = EXPORT_DIR / fname
    i = 1
    stem = out_path.stem
    while out_path.exists():
        out_path = EXPORT_DIR / f"{stem}_{i}.md"
        i += 1
    out_path.write_text(md_text, encoding="utf-8")

    return jsonify({
        "ok": True, "session_id": sid,
        "filename": out_path.name,
        "size_kb": round(out_path.stat().st_size / 1024, 1),
        "download_url": f"/download/{out_path.name}",
        "stats": meta,
    })


@app.get("/api/export_all")
def api_export_all():
    """一键导出所有会话的对话记录 zip；source=all 时两个数据源一起导。"""
    raw = (request.args.get("source") or "solo").strip().lower()
    src_list = list(SOURCES.keys()) if raw == "all" else [get_source()]
    buf = io.BytesIO()
    ok = 0
    failed = []
    any_found = False
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in src_list:
            sessions = db_sessions(src)
            if sessions is None:
                failed.append(f"{SOURCES[src]['label']}: 解密库不存在")
                continue
            if sessions:
                any_found = True
            prefix = SOURCES[src]["prefix"]
            for s in sessions:
                sid = s["id"]
                try:
                    md_text, meta = build_chat_md(sid, src)
                except Exception as e:
                    failed.append(f"{sid}: {type(e).__name__}: {e}")
                    continue
                if md_text is None:
                    failed.append(f"{sid}: {meta}")
                    continue
                fname = f"{prefix}_{safe_filename(meta['title'])}_{sid[:8]}.md"
                zf.writestr(fname, md_text)
                ok += 1
    if not any_found:
        msg = "未找到任何会话" + ("；".join(failed) if failed else "")
        return jsonify({"ok": False, "error": msg})
    if failed:
        repack = io.BytesIO()
        # 失败清单并入 zip（原 buf 已关闭，重新打包）
        buf.seek(0)
        with zipfile.ZipFile(buf) as zin, zipfile.ZipFile(repack, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item.filename))
            zout.writestr("_导出失败清单.txt",
                          "以下会话导出失败（数据异常，不影响其余文件）：\n\n" + "\n".join(failed))
        buf = repack
    buf.seek(0)
    fname = f"trae_chats_{raw}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/zip")


@app.get("/download/<path:filename>")
def download(filename):
    return send_from_directory(str(EXPORT_DIR), filename, as_attachment=True)


# ---------- 前端页面 ----------
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trae 对话记录导出器</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #0f1117; color: #e6e6e6; min-height: 100vh;
    display: flex; justify-content: center; padding: 48px 16px;
  }
  .card { width: 100%; max-width: 720px; background: #1a1d27; border: 1px solid #2a2e3d; border-radius: 14px; padding: 32px; box-shadow: 0 8px 30px rgba(0,0,0,.4); }
  h1 { font-size: 22px; margin-bottom: 6px; }
  .sub { color: #8b93a7; font-size: 13px; margin-bottom: 24px; }
  label { display: block; font-size: 13px; color: #aab2c5; margin-bottom: 8px; }
  input[type=text] { width: 100%; padding: 12px 14px; font-size: 14px; color: #e6e6e6; background: #12141d; border: 1px solid #2f3446; border-radius: 8px; font-family: Consolas, "Courier New", monospace; outline: none; }
  input[type=text]:focus { border-color: #4f7cff; }
  .btn-row { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  button { flex: 1; min-width: 120px; padding: 11px 0; font-size: 14px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; transition: opacity .15s; }
  button:hover { opacity: .85; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  #btnInfo { background: #2a2f45; color: #c9d2e8; }
  #btnExport { background: #4f7cff; color: #fff; }
  #btnAll { background: #30a46c; color: #fff; }
  .src-btn { background: #2a2f45; color: #c9d2e8; flex: 1; }
  .src-btn.active { background: #4f7cff; color: #fff; }
  .box { margin-top: 20px; padding: 16px; border-radius: 10px; font-size: 13px; background: #12141d; border: 1px solid #2f3446; display: none; white-space: pre-wrap; word-break: break-all; line-height: 1.7; }
  .box.error { border-color: #e5484d; color: #ff9b9b; }
  .box.info { border-color: #2f3446; color: #b8c1d6; }
  .box.success { border-color: #30a46c; color: #a7e8c5; }
  .box a { color: #4f7cff; }
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; }
  .kv b { color: #8b93a7; font-weight: 500; }
  .list { margin-top: 8px; max-height: 300px; overflow-y: auto; border: 1px solid #2f3446; border-radius: 8px; }
  .list-item { padding: 8px 12px; border-bottom: 1px solid #232838; cursor: pointer; font-size: 12px; display: flex; justify-content: space-between; gap: 8px; align-items: center; }
  .list-item:hover { background: #232838; }
  .list-item code { color: #7ea6ff; }
  .li-left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .li-name { color: #e6e6e6; font-size: 13px; font-weight: 600; }
  .muted { color: #5d6577; }
  .hint { margin-top: 22px; font-size: 12px; color: #5d6577; line-height: 1.8; }
  code { background: #232838; padding: 1px 6px; border-radius: 4px; font-family: Consolas, monospace; }
</style>
</head>
<body>
<div class="card">
  <h1>💬 Trae 对话记录导出器</h1>
  <div class="sub">从解密数据库导出真正的对话记录（user / assistant 交替），支持 Trae Work 与 Trae CN</div>

  <label>数据源</label>
  <div class="btn-row" style="margin-top:0">
    <button id="srcSolo" class="src-btn active" onclick="switchSource('solo')">Trae Work（SOLO）</button>
    <button id="srcCn" class="src-btn" onclick="switchSource('cn')">Trae CN</button>
    <button id="srcAll" class="src-btn" onclick="switchSource('all')">全部</button>
  </div>

  <label for="sid">Session ID（20 位十六进制，可留空直接从列表点选）</label>
  <input type="text" id="sid" placeholder="6a70ab366e07f4b94dafacbf" autocomplete="off" onkeydown="if(event.key==='Enter')doExport()">

  <div class="btn-row">
    <button id="btnList" onclick="loadSessions()">加载会话列表</button>
    <button id="btnInfo" onclick="queryInfo()">查询会话信息</button>
    <button id="btnExport" onclick="doExport()">导出对话 MD</button>
    <button id="btnAll" onclick="exportAll()">一键导出所有</button>
  </div>

  <div id="sessionList" class="list" style="display:none"></div>
  <div id="box" class="box"></div>

  <div class="hint">
    对话数据来自解密数据库（<code>decrypt_tool\\database_decrypted.db</code> / <code>database_traecn_decrypted.db</code>）。
    <br>标题或列表为空时，先双击 <code>decrypt_tool\\刷新密钥并解密.bat</code>（需 Trae 在运行），然后 Ctrl+F5 刷新本页。
    <br>MD 格式：<code>## user</code> / <code>## assistant</code> 交替，含全部对话文本。
  </div>
</div>

<script>
var $sid, $box, $list, btns;
function initRefs() {
  $sid = document.getElementById('sid');
  $box = document.getElementById('box');
  $list = document.getElementById('sessionList');
  btns = [document.getElementById('btnList'), document.getElementById('btnInfo'), document.getElementById('btnExport'), document.getElementById('btnAll')];
}
initRefs();

function show(kind, html) {
  $box.className = 'box ' + kind;
  $box.style.display = 'block';
  $box.innerHTML = html;
}
function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function setBusy(b) { btns.forEach(function (x) { x.disabled = b; }); }
function sid() { return $sid.value.trim().toLowerCase(); }
async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}

var curSource = 'solo';
function switchSource(s) {
  curSource = s;
  ['srcSolo', 'srcCn', 'srcAll'].forEach(function (id) {
    document.getElementById(id).classList.remove('active');
  });
  var map = { solo: 'srcSolo', cn: 'srcCn', all: 'srcAll' };
  document.getElementById(map[s]).classList.add('active');
  $list.style.display = 'none';
}

function pickSession(id) { $sid.value = id; $list.style.display = 'none'; }

async function loadSessions() {
  setBusy(true);
  try {
    const r = await fetch('/api/sessions?source=' + curSource);
    const d = await r.json();
    if (!d.ok) { show('error', esc(d.error)); return; }
    if (!d.sessions.length) { show('info', '当前数据源没有任何会话'); return; }
    $list.style.display = 'block';
    $list.innerHTML = d.sessions.map(function (s) {
      return '<div class="list-item" onclick="pickSession(&quot;' + esc(s.id) + '&quot;)">' +
        '<span class="li-left">' +
        (s.title ? '<span class="li-name">' + esc(s.title) + '</span>' : '') +
        '<code>' + esc(s.id) + '</code>' +
        '</span>' +
        '<span class="muted">' + s.turns + ' 轮 · ' + esc(s.updated || s.created || '?') + '</span>' +
        '</div>';
    }).join('');
    show('info', '共 ' + d.sessions.length + ' 个会话，点击列表项填入 ID');
  } catch (e) { show('error', '请求失败：' + esc(e.message)); }
  finally { setBusy(false); }
}

async function queryInfo() {
  const id = sid();
  if (!id) { show('error', '请先粘贴或点选 Session ID'); return; }
  setBusy(true); show('info', '查询中…');
  try {
    const d = await post('/api/info', { session_id: id, source: curSource });
    if (!d.ok) { show('error', esc(d.error)); return; }
    show('success',
      '<div class="kv">' +
      '<b>标题</b><span>' + esc(d.title) + '</span>' +
      '<b>数据源</b><span>' + esc(d.source) + '</span>' +
      '<b>Session ID</b><span><code>' + esc(d.session_id) + '</code></span>' +
      '<b>轮数</b><span>' + d.turns + '（消息 ' + d.messages + ' 条）</span>' +
      '<b>创建</b><span>' + esc(d.created) + '</span>' +
      '<b>更新</b><span>' + esc(d.updated) + '</span>' +
      '</div>'
    );
  } catch (e) { show('error', '请求失败：' + esc(e.message)); }
  finally { setBusy(false); }
}

async function doExport() {
  const id = sid();
  if (!id) { show('error', '请先粘贴或点选 Session ID'); return; }
  setBusy(true); show('info', '正在生成对话 Markdown…');
  try {
    const d = await post('/api/export', { session_id: id, source: curSource });
    if (!d.ok) { show('error', esc(d.error)); return; }
    const s = d.stats || {};
    show('success',
      '<div class="kv">' +
      '<b>标题</b><span>' + esc(s.title) + '</span>' +
      '<b>轮数</b><span>' + s.turns + '（消息 ' + s.messages + ' 条）</span>' +
      '<b>总字数</b><span>' + s.chars + '</span>' +
      '<b>文件大小</b><span>' + d.size_kb + ' KB</span>' +
      '</div>' +
      '<p style="margin-top:12px"><a href="' + esc(d.download_url) + '">⬇ 下载 ' + esc(d.filename) + '</a></p>'
    );
  } catch (e) { show('error', '请求失败：' + esc(e.message)); }
  finally { setBusy(false); }
}

async function exportAll() {
  setBusy(true); show('info', '正在打包全部对话记录（会话较多时可能需要一些时间）…');
  try {
    const r = await fetch('/api/export_all?source=' + curSource);
    if (!r.ok) {
      let d = null; try { d = await r.json(); } catch (e) {}
      show('error', (d && d.error) ? esc(d.error) : ('请求失败：HTTP ' + r.status));
      return;
    }
    let fname = 'trae_chats.zip';
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^";]+)"?/);
    if (m) fname = decodeURIComponent(m[1]);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fname;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    show('success', '已打包全部对话记录并开始下载 <code>' + esc(fname) + '</code>');
  } catch (e) { show('error', '请求失败：' + esc(e.message)); }
  finally { setBusy(false); }
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("=" * 52)
    print(" Trae 对话记录导出器")
    for k, v in SOURCES.items():
        print(f" 数据源[{k}]: {v['label']}")
        print(f"   解密库: {v['decrypted_db']}")
    print(f" 导出目录: {EXPORT_DIR}")
    print(" 打开浏览器访问: http://127.0.0.1:5001")
    print(" 按 Ctrl+C 停止服务")
    print("=" * 52)
    app.run(host="127.0.0.1", port=5001, debug=False)
