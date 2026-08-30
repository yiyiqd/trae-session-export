# -*- coding: utf-8 -*-
"""
Trae 快照 git 仓库解析库（纯 Python，无需 git 命令）。
快照位置：%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\snapshot\<session_id>\v2\.git
"""
import os
import re
import zlib
from datetime import datetime


class GitRepo:
    def __init__(self, git_dir):
        self.git_dir = git_dir
        self.objects_dir = os.path.join(git_dir, "objects")
        self._cache = {}

    def read_object(self, sha):
        """读取 git object，返回 (type, content)。"""
        if sha in self._cache:
            return self._cache[sha]
        path = os.path.join(self.objects_dir, sha[:2], sha[2:])
        if not os.path.exists(path):
            return None, None
        with open(path, "rb") as f:
            raw = zlib.decompress(f.read())
        null = raw.index(b"\x00")
        typ = raw[:null].decode("ascii").split(" ")[0]
        content = raw[null + 1:]
        self._cache[sha] = (typ, content)
        return typ, content

    def read_blob_text(self, sha):
        typ, content = self.read_object(sha)
        if typ != "blob":
            return None
        return content.decode("utf-8", errors="replace")

    @staticmethod
    def parse_commit(content):
        lines = content.split(b"\n")
        tree, parents, author, committer, message = None, [], "", "", ""
        idx = 0
        for i, line in enumerate(lines):
            if line == b"":
                idx = i + 1
                break
            if line.startswith(b"tree "):
                tree = line[5:].decode()
            elif line.startswith(b"parent "):
                parents.append(line[7:].decode())
            elif line.startswith(b"author "):
                author = line[7:].decode()
            elif line.startswith(b"committer "):
                committer = line[7:].decode()
        message = b"\n".join(lines[idx:]).decode("utf-8", errors="replace").strip()
        ts = None
        m = re.search(r"(\d{10}) ([+-]\d{4})", committer)
        if m:
            ts = int(m.group(1))
        return tree, parents, author, committer, message, ts

    @staticmethod
    def parse_tree(content):
        entries = []
        i = 0
        while i < len(content):
            sp = content.index(b" ", i)
            mode = content[i:sp].decode()
            null = content.index(b"\x00", sp)
            name = content[sp + 1:null].decode("utf-8", errors="replace")
            sha = content[null + 1:null + 21].hex()
            entries.append((name, mode, sha))
            i = null + 21
        return entries

    def walk_tree(self, sha, prefix=""):
        """递归遍历 tree，返回 [(path, mode, sha)]（仅文件）。"""
        result = []
        typ, content = self.read_object(sha)
        if typ != "tree":
            return result
        for name, mode, sub_sha in self.parse_tree(content):
            path = f"{prefix}/{name}" if prefix else name
            if mode in ("40000", "040000"):
                result.extend(self.walk_tree(sub_sha, path))
            else:
                result.append((path, mode, sub_sha))
        return result

    def tree_files_map(self, sha):
        """返回 {path: blob_sha}"""
        return {p: s for p, _, s in self.walk_tree(sha)}

    def read_ref(self, ref_name):
        """读取 ref 指向的 commit sha。"""
        path = os.path.join(self.git_dir, ref_name)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()

    def get_branches(self):
        """列出所有本地分支名 -> commit sha。"""
        heads = os.path.join(self.git_dir, "refs", "heads")
        result = {}
        if os.path.isdir(heads):
            for name in os.listdir(heads):
                sha = self.read_ref(os.path.join("refs", "heads", name))
                if sha:
                    result[name] = sha
        return result

    def get_tags(self):
        """列出所有标签名 -> commit sha。"""
        tags = os.path.join(self.git_dir, "refs", "tags")
        result = {}
        if os.path.isdir(tags):
            for name in os.listdir(tags):
                sha = self.read_ref(os.path.join("refs", "tags", name))
                if sha:
                    result[name] = sha
        return result

    def get_commit_log(self, branch):
        """读取分支日志，返回 [(sha, message)] 按时间正序。"""
        log_file = os.path.join(self.git_dir, "logs", "refs", "heads", branch)
        if not os.path.exists(log_file):
            return []
        commits = []
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 2:
                    continue
                meta = parts[0].split(" ")
                if len(meta) >= 3 and len(meta[1]) == 40 and meta[1] != "unknown":
                    commits.append((meta[1], parts[1]))
        return commits


def extract_project_names(repo, branch, limit=2):
    """从会话最新提交的树中提取项目/工作区文件夹名（root_path_prefix_xxx/<name>/...）。"""
    log = repo.get_commit_log(branch)
    if not log:
        return []
    typ, content = repo.read_object(log[-1][0])
    if typ != "commit":
        return []
    tree, _, _, _, _, _ = repo.parse_commit(content)
    if not tree:
        return []
    names = []
    seen = set()
    for path, _, _ in repo.walk_tree(tree):
        m = re.search(r"root_path_prefix_[0-9a-f]+[/\\]+([^/\\]+)", path)
        if m:
            n = m.group(1)
            # 跳过明显是文件名的项（带扩展名）
            if "." in n and not n.replace(".", "").isalnum():
                continue
            if n not in seen:
                seen.add(n)
                names.append(n)
            if len(names) >= limit:
                break
    return names


def find_session_dirs(snapshot_root):
    """扫描 snapshot 根目录，返回所有会话目录的完整路径。"""
    result = []
    if not os.path.isdir(snapshot_root):
        return result
    for d in os.listdir(snapshot_root):
        v2 = os.path.join(snapshot_root, d, "v2")
        if os.path.isdir(os.path.join(v2, ".git")):
            result.append(os.path.join(snapshot_root, d))
    return result


def diff_trees(old_map, new_map):
    """对比两个文件树，返回变更列表 [(path, action)]，action in add/modify/delete。"""
    changes = []
    all_paths = set(old_map) | set(new_map)
    for path in all_paths:
        old_sha = old_map.get(path)
        new_sha = new_map.get(path)
        if old_sha is None:
            changes.append((path, "add"))
        elif new_sha is None:
            changes.append((path, "delete"))
        elif old_sha != new_sha:
            changes.append((path, "modify"))
    changes.sort()
    return changes


def format_ts(ts):
    if not ts:
        return "unknown"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)
