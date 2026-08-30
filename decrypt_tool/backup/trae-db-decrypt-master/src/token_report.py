"""
Trae SOLO Token 使用量分析报告
从解密后的 database_decrypted.db 中提取 token 使用统计

用法:
  python src/token_report.py                              # 默认 database_decrypted.db
  python src/token_report.py -d /path/to/decrypted.db    # 指定数据库
"""
import argparse
import sqlite3, json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

parser = argparse.ArgumentParser(description="Trae SOLO Token 使用量分析")
parser.add_argument("-d", "--db", default="database_decrypted.db", help="解密后的数据库路径")
args = parser.parse_args()

conn = sqlite3.connect(args.db)
tz_cn = timezone(timedelta(hours=8))

sp_rows = conn.execute('SELECT session_id, project_id FROM session_project').fetchall()
session_project = {r[0]: r[1] for r in sp_rows}

proj_rows = conn.execute('SELECT project_id, absolute_path FROM project').fetchall()
proj_names = {}
for r in proj_rows:
    if r[1]:
        proj_names[r[0]] = r[1].replace('\\', '/').split('/')[-1]
    else:
        proj_names[r[0]] = r[0][:12]

rows = conn.execute('SELECT session_id, context FROM chat_turn WHERE context IS NOT NULL').fetchall()

session_tokens = defaultdict(lambda: {'total': 0, 'prompt': 0, 'completion': 0, 'count': 0})
for session_id, ctx_str in rows:
    try:
        ctx = json.loads(ctx_str)
        tu = ctx.get('token_usage', {})
        if tu and tu.get('total_tokens', 0) > 0:
            session_tokens[session_id]['total'] += tu['total_tokens']
            session_tokens[session_id]['prompt'] += tu.get('prompt_tokens', 0)
            session_tokens[session_id]['completion'] += tu.get('completion_tokens', 0)
            session_tokens[session_id]['count'] += 1
    except:
        continue

project_tokens = defaultdict(lambda: {'total': 0, 'prompt': 0, 'completion': 0, 'count': 0, 'sessions': 0})
for sid, stats in session_tokens.items():
    pid = session_project.get(sid, 'unknown')
    pname = proj_names.get(pid, pid[:12] if pid else 'unknown')
    project_tokens[pname]['total'] += stats['total']
    project_tokens[pname]['prompt'] += stats['prompt']
    project_tokens[pname]['completion'] += stats['completion']
    project_tokens[pname]['count'] += stats['count']
    project_tokens[pname]['sessions'] += 1

print('【按项目 Token 使用量】')
print(f'{"项目":<35} {"会话":>5} {"调用":>7} {"Prompt":>12} {"Completion":>11} {"Total":>12}')
print('-' * 86)
for proj, stats in sorted(project_tokens.items(), key=lambda x: -x[1]['total']):
    name = proj if len(proj) <= 33 else proj[:30] + '...'
    print(f'{name:<35} {stats["sessions"]:>5} {stats["count"]:>7,} {stats["prompt"]:>12,} {stats["completion"]:>11,} {stats["total"]:>12,}')

print()
print('【按日期 Token 使用量】')
rows2 = conn.execute('SELECT created_at, context FROM chat_turn WHERE context IS NOT NULL').fetchall()

day_stats = defaultdict(lambda: {'total': 0, 'prompt': 0, 'completion': 0, 'count': 0})
for ts, ctx_str in rows2:
    try:
        ctx = json.loads(ctx_str)
        tu = ctx.get('token_usage', {})
        if tu and tu.get('total_tokens', 0) > 0:
            day = datetime.fromtimestamp(ts, tz=tz_cn).strftime('%Y-%m-%d')
            day_stats[day]['total'] += tu['total_tokens']
            day_stats[day]['prompt'] += tu.get('prompt_tokens', 0)
            day_stats[day]['completion'] += tu.get('completion_tokens', 0)
            day_stats[day]['count'] += 1
    except:
        continue

grand_prompt = sum(s['prompt'] for s in day_stats.values())
print(f'{"日期":<12} {"调用":>6} {"Prompt":>12} {"Completion":>11} {"Total":>12} {"Prompt占比":>10}')
print('-' * 66)
for day in sorted(day_stats.keys()):
    s = day_stats[day]
    prompt_pct = s['prompt'] / grand_prompt * 100 if grand_prompt > 0 else 0
    print(f'{day:<12} {s["count"]:>6,} {s["prompt"]:>12,} {s["completion"]:>11,} {s["total"]:>12,} {prompt_pct:>9.1f}%')

grand_total = sum(s['total'] for s in day_stats.values())
grand_completion = sum(s['completion'] for s in day_stats.values())
print(f'{"总计":<12} {sum(s["count"] for s in day_stats.values()):>6,} {grand_prompt:>12,} {grand_completion:>11,} {grand_total:>12,}')
