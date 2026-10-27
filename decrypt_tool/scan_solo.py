# -*- coding: utf-8 -*-
"""适配 TRAE SOLO CN 的密钥扫描器（基于 Oh-My-Trae/trae-db-decrypt 的 scan_memory.py）

新版适配（2026-10）：
- 新版 Trae 已不再加载 ai_agent.dll，不再按模块过滤，改为扫描
  TRAE SOLO CN / Trae CN 的全部进程实例，密钥由 HMAC-SHA512 校验确认；
- TRAE SOLO CN 未运行时自动改用 Trae CN 的进程和数据库作参考
  （两程序加密机制相同，本机密钥通用）。
"""
import os
import sys
import json
import time
import ctypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_memory as sm

kernel32 = ctypes.windll.kernel32
PROCESS_NAMES = ("TRAE SOLO CN.exe", "Trae CN.exe")
DB_CANDIDATES = [
    os.path.join(os.environ.get("APPDATA", ""), "TRAE SOLO CN", "ModularData", "ai-agent", "database.db"),
    os.path.join(os.environ.get("APPDATA", ""), "Trae CN", "ModularData", "ai-agent", "database.db"),
]


def main():
    print("=" * 60)
    print("  TRAE SOLO CN / Trae CN Database Key Scanner")
    print("=" * 60)

    # 参考数据库：SOLO 优先，否则用 Trae CN（加密机制相同，密钥通用）
    db_path = next((p for p in DB_CANDIDATES if os.path.exists(p)), None)
    if not db_path:
        print("[!] No database found:")
        for p in DB_CANDIDATES:
            print("    ", p)
        sys.exit(1)
    db_info = sm.load_database_info(db_path)
    print(f"[+] DB: {db_path}")
    print(f"[+] Salt: {db_info['salt']}  Size: {os.path.getsize(db_path)//1024//1024}MB")

    candidates = sm.get_candidate_pids(PROCESS_NAMES)
    if not candidates:
        print("[!] No TRAE SOLO CN / Trae CN processes found")
        sys.exit(1)
    print(f"[+] {len(candidates)} candidate process(es), sqlite3.node holders first")

    result = None
    for idx, pid in enumerate(candidates, 1):
        h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not h:
            print(f"[{idx}/{len(candidates)}] Cannot open process PID={pid}, skip")
            continue
        try:
            regions = sm.enum_regions(h)
            total_mb = sum(s for _, s in regions) / 1024 / 1024
            print(f"[{idx}/{len(candidates)}] PID={pid}: {total_mb:.0f}MB in {len(regions)} regions")
            t0 = time.time()
            found, cands = sm.scan_memory(h, regions, db_info, print)
            print(f"  scan {time.time()-t0:.1f}s  verified={len(found)} candidates={len(cands)}")
            if found:
                result = {"db_path": db_path, "salt": db_info["salt"],
                          "enc_key": found[0]["key"], "address": found[0]["addr"]}
                break
        finally:
            kernel32.CloseHandle(h)

    if not result:
        print("[!] no verified key in any process")
        sys.exit(1)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decrypted_key.json")
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print("[+] VERIFIED KEY:", result["enc_key"])
    print("[+] saved:", out)


if __name__ == "__main__":
    main()
