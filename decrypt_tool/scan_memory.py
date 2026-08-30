"""
Scan Trae CN process memory for SQLCipher encryption key.
Inspired by wechat-decrypt: https://github.com/ylytdeng/wechat-decrypt

Uses Windows API directly (no Frida) to:
1. Find ai_agent.dll process
2. Read all committed, readable memory regions
3. Search for hex key patterns
4. Verify candidates with HMAC-SHA512 against database page 1
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import hmac as hmac_mod
import json
import os
import re
import struct
import subprocess
import sys
import time

kernel32 = ctypes.windll.kernel32
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD),
        ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("_pad2", wt.DWORD),
    ]


def get_ai_agent_pid():
    try:
        out = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq Trae CN.exe" /FO CSV /NH',
            shell=True, text=True, errors='replace', timeout=5
        )
    except Exception:
        return None

    pids = []
    for line in out.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.strip('"').split('","')
        if len(parts) >= 5:
            try:
                pid = int(parts[1])
                mem = int(parts[4].replace(',', '').replace(' K', '').strip() or '0')
                pids.append((pid, mem))
            except Exception:
                pass

    if not pids:
        print("[!] No Trae CN processes found")
        return None

    pids.sort(key=lambda x: x[1], reverse=True)

    for pid, mem in pids:
        try:
            out = subprocess.check_output(
                f'tasklist /FI "PID eq {pid}" /M /FO CSV /NH',
                shell=True, text=True, errors='replace', timeout=5
            )
            if 'ai_agent' in out.lower():
                print(f"[+] Found ai_agent.dll in PID {pid} ({mem // 1024}MB)")
                return pid
        except Exception:
            pass

    try:
        import frida
        for pid, mem in pids:
            try:
                s = frida.attach(pid)
                sc = s.create_script(
                    "rpc.exports={f:function(){var a=Process.enumerateModules().filter("
                    "function(m){return m.name.toLowerCase().indexOf('ai_agent')!==-1;});"
                    "return a.length>0?a[0].base.toString():null;}};"
                )
                sc.load()
                r = sc.exports_sync.f()
                s.detach()
                if r:
                    print(f"[+] Found ai_agent.dll in PID {pid} ({mem // 1024}MB)")
                    return pid
            except Exception:
                pass
    except ImportError:
        pass

    print("[!] ai_agent.dll not found in any process")
    return None


def read_mem(h, addr, sz):
    buf = ctypes.create_string_buffer(sz)
    n = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, sz, ctypes.byref(n)):
        return buf.raw[:n.value]
    return None


def enum_regions(h):
    regs = []
    addr = 0
    mbi = MBI()
    while addr < 0x7FFFFFFFFFFF:
        if kernel32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and 0 < mbi.RegionSize < 500 * 1024 * 1024:
            regs.append((mbi.BaseAddress, mbi.RegionSize))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return regs


def verify_enc_key(enc_key, db_page1):
    try:
        salt = db_page1[:SALT_SZ]
        mac_salt = bytes(b ^ 0x3A for b in salt)
        mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
        hmac_data = db_page1[SALT_SZ: PAGE_SZ - 80 + 16]
        stored_hmac = db_page1[PAGE_SZ - 64: PAGE_SZ]
        hm = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
        hm.update(struct.pack("<I", 1))
        return hm.digest() == stored_hmac
    except Exception:
        return False


def load_database_info(db_path):
    if not os.path.exists(db_path):
        return None
    with open(db_path, "rb") as f:
        page1 = f.read(PAGE_SZ)
    salt = page1[:SALT_SZ]
    return {"path": db_path, "page1": page1, "salt": salt.hex()}


def scan_memory(h, regions, db_info, print_fn=print):
    salt_hex = db_info["salt"]
    page1 = db_info["page1"]
    patterns = [
        re.compile(rb"x'([0-9a-fA-F]{64,192})'"),
        re.compile(rb"'([0-9a-fA-F]{64})'"),
        re.compile(rb"([0-9a-fA-F]{64})"),
    ]
    total_bytes = sum(s for _, s in regions)
    scanned = 0
    found_keys = []
    candidates = []

    for reg_idx, (base, size) in enumerate(regions):
        data = read_mem(h, base, size)
        scanned += size
        if not data:
            continue

        for pat in patterns:
            for m in pat.finditer(data):
                hex_str = m.group(1).decode() if m.lastindex else m.group(0).decode()
                addr = base + m.start()
                hex_len = len(hex_str)

                enc_key_hex = None
                matched_salt = None

                if hex_len == 96:
                    enc_key_hex = hex_str[:64]
                    matched_salt = hex_str[64:]
                elif hex_len == 64:
                    enc_key_hex = hex_str
                    matched_salt = salt_hex
                elif hex_len > 96 and hex_len % 2 == 0:
                    enc_key_hex = hex_str[:64]
                    matched_salt = hex_str[-32:]
                else:
                    continue

                if matched_salt == salt_hex:
                    enc_key = bytes.fromhex(enc_key_hex)
                    if verify_enc_key(enc_key, page1):
                        found_keys.append({"key": enc_key_hex, "addr": hex(addr)})
                        print_fn(f"\n  [FOUND] Key verified!")
                        print_fn(f"    enc_key={enc_key_hex}")
                        print_fn(f"    Address: 0x{addr:016X}")
                        return found_keys, candidates
                    else:
                        candidates.append({"key": enc_key_hex, "addr": hex(addr)})

        if (reg_idx + 1) % 100 == 0:
            progress = scanned / total_bytes * 100 if total_bytes else 100
            print_fn(f"  [{progress:.1f}%] scanned {scanned // 1024 // 1024}MB, {len(candidates)} candidates")

    return found_keys, candidates


def find_database():
    """自动检测 Trae CN database.db 路径"""
    import argparse
    import pathlib

    default_paths = [
        pathlib.Path(os.environ.get("APPDATA", "")) / "Trae CN" / "ModularData" / "ai-agent" / "database.db",
    ]

    # 尝试默认路径
    for p in default_paths:
        if p.exists():
            return str(p)

    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Trae CN 数据库密钥扫描器")
    parser.add_argument("-d", "--db-path", help="database.db 路径（默认自动检测）")
    args = parser.parse_args()

    print("=" * 60)
    print("  Trae CN Database Key Scanner")
    print("  (Inspired by wechat-decrypt)")
    print("=" * 60)

    db_path = args.db_path or find_database()
    if not db_path or not os.path.exists(db_path):
        print("[!] Database not found. Use -d to specify the path.")
        print("    Expected: %APPDATA%/Trae CN/ModularData/ai-agent/database.db")
        sys.exit(1)

    db_info = load_database_info(db_path)
    print(f"[+] Database: {db_path}")
    print(f"[+] Salt: {db_info['salt']}")
    print(f"[+] Size: {os.path.getsize(db_path) // 1024 // 1024}MB")

    pid = get_ai_agent_pid()
    if not pid:
        print("[!] Cannot find process with ai_agent.dll")
        sys.exit(1)

    h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        print(f"[!] Cannot open process PID={pid}")
        sys.exit(1)

    try:
        regions = enum_regions(h)
        total_mb = sum(s for _, s in regions) / 1024 / 1024
        print(f"[+] Process PID={pid}: {total_mb:.0f}MB in {len(regions)} regions")

        t0 = time.time()
        found_keys, candidates = scan_memory(h, regions, db_info, print)
        elapsed = time.time() - t0

        print(f"\n{'=' * 60}")
        print(f"Scan complete: {elapsed:.1f}s")
        print(f"Found: {len(found_keys)} verified keys")
        print(f"Candidates: {len(candidates)} (HMAC failed)")

        if found_keys:
            print(f"\n[+] VERIFIED KEY: {found_keys[0]['key']}")
            result = {
                "db_path": db_path,
                "salt": db_info["salt"],
                "enc_key": found_keys[0]["key"],
                "address": found_keys[0]["addr"]
            }
            out_path = os.path.join(os.getcwd(), "decrypted_key.json")
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            print(f"[+] Key saved to {out_path}")
        elif candidates:
            print(f"\n[!] No verified keys found")
            for c in candidates[:10]:
                print(f"    {c['key']} @ {c['addr']}")
        else:
            print(f"\n[!] No hex patterns found in memory")

    finally:
        kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
