# -*- coding: utf-8 -*-
"""适配 TRAE SOLO CN 的密钥扫描器（基于 Oh-My-Trae/trae-db-decrypt 的 scan_memory.py）"""
import os
import sys
import json
import time
import ctypes
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_memory as sm

kernel32 = ctypes.windll.kernel32
PROCESS_NAME = "TRAE SOLO CN.exe"
DB_PATH = os.path.join(os.environ.get("APPDATA", ""), "TRAE SOLO CN", "ModularData", "ai-agent", "database.db")


def get_solo_pid():
    try:
        out = subprocess.check_output(
            f'tasklist /FI "IMAGENAME eq {PROCESS_NAME}" /FO CSV /NH',
            shell=True, text=True, errors="replace", timeout=10)
    except Exception as e:
        print("[!] tasklist err:", e)
        return None
    pids = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip('"').split('","')
        if len(parts) >= 5:
            try:
                pids.append((int(parts[1]), int(parts[4].replace(",", "").replace(" K", "").strip() or "0")))
            except Exception:
                pass
    if not pids:
        print("[!] No TRAE SOLO CN processes")
        return None
    pids.sort(key=lambda x: x[1], reverse=True)
    for pid, mem in pids:
        try:
            out = subprocess.check_output(f'tasklist /FI "PID eq {pid}" /M /FO CSV /NH',
                                          shell=True, text=True, errors="replace", timeout=10)
            if "ai_agent" in out.lower():
                print(f"[+] ai_agent.dll in PID {pid} ({mem // 1024}MB)")
                return pid
        except Exception:
            pass
    # 没找到 ai_agent 就返回内存最大的
    print("[!] ai_agent not matched; use largest PID", pids[0][0])
    return pids[0][0]


def main():
    print("=" * 60)
    print("  TRAE SOLO CN Database Key Scanner")
    print("=" * 60)
    if not os.path.exists(DB_PATH):
        print("[!] DB not found:", DB_PATH)
        sys.exit(1)
    db_info = sm.load_database_info(DB_PATH)
    print(f"[+] DB: {DB_PATH}")
    print(f"[+] Salt: {db_info['salt']}  Size: {os.path.getsize(DB_PATH)//1024//1024}MB")

    pid = get_solo_pid()
    if not pid:
        sys.exit(1)
    h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        print("[!] Cannot open process", pid)
        sys.exit(1)
    try:
        regions = sm.enum_regions(h)
        total_mb = sum(s for _, s in regions) / 1024 / 1024
        print(f"[+] PID={pid}: {total_mb:.0f}MB in {len(regions)} regions")
        t0 = time.time()
        found, cands = sm.scan_memory(h, regions, db_info, print)
        print(f"\nScan {time.time()-t0:.1f}s  found={len(found)} candidates={len(cands)}")
        if found:
            result = {"db_path": DB_PATH, "salt": db_info["salt"], "enc_key": found[0]["key"], "address": found[0]["addr"]}
            out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decrypted_key.json")
            with open(out, "w") as f:
                json.dump(result, f, indent=2)
            print("[+] VERIFIED KEY:", found[0]["key"])
            print("[+] saved:", out)
        else:
            print("[!] no verified key; top candidates:")
            for c in cands[:10]:
                print("   ", c["key"], c["addr"])
    finally:
        kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
