"""
导出 Trae CN 聊天记录示例
"""
import sqlite3
import json

def export_chats(db_path, key):
    """导出所有聊天记录"""
    db = sqlite3.connect(db_path)
    db.execute(f"PRAGMA key = '{key}'")
    
    # 获取所有会话
    sessions = db.execute("""
        SELECT s.session_id, s.session_title, s.session_type,
               COUNT(h.id) as message_count
        FROM chat_session s
        LEFT JOIN history_v2 h ON s.session_id = h.session_id
        GROUP BY s.session_id
        ORDER BY message_count DESC
    """).fetchall()
    
    print(f"Found {len(sessions)} sessions:")
    for s in sessions[:10]:
        print(f"  [{s[2]}] {s[1] or 'Untitled'} ({s[3]} messages)")
    
    # 导出第一个会话的完整对话
    if sessions:
        session_id = sessions[0][0]
        print(f"\nExporting session: {sessions[0][1]}")
        
        history = db.execute("""
            SELECT messages, agent_type, created_at
            FROM history_v2
            WHERE session_id = ?
            ORDER BY created_at
        """, (session_id,)).fetchall()
        
        for h in history:
            if h[0]:
                try:
                    msg_data = json.loads(h[0])
                    if 'raw_messages' in msg_data:
                        for msg in msg_data['raw_messages']:
                            role = msg.get('role', '')
                            content = msg.get('content', [])
                            text = ' '.join([p.get('text', '') for p in content if p.get('type') == 'text'])
                            if text:
                                print(f"\n[{role}]")
                                print(text[:500])
                except:
                    pass
    
    db.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python export_chats.py <database.db> <key>")
        print("Example: python export_chats.py database.db \"x'3605...\"")
        sys.exit(1)
    
    export_chats(sys.argv[1], sys.argv[2])
