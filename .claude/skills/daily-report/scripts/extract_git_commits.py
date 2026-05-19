#!/usr/bin/env python3
"""
从 git 仓库提取提交记录，输出结构化 JSON，供 daily-report skill 使用。

用法：
    python extract_git_commits.py [--since "today 00:00"] [--author "me"] [--repo PATH]

输出：标准输出一段 JSON 数组，每个元素结构如下：
    {
        "sha": "abc1234",
        "subject": "fix: ...",
        "author": "张三",
        "datetime": "2026-05-19 14:30:11 +0800",
        "files_changed": ["src/a.py", "tests/test_a.py"]
    }
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_git(args, cwd):
    """执行 git 命令并返回标准输出；失败时直接退出进程。"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[错误] git {' '.join(args)} 执行失败：\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("[错误] 系统 PATH 中未找到 git 命令", file=sys.stderr)
        sys.exit(1)


def extract_commits(since, author, repo):
    """按筛选条件提取提交记录，返回字典列表。"""
    repo_path = Path(repo).resolve()
    if not (repo_path / ".git").exists():
        print(f"[错误] {repo_path} 不是一个 git 仓库", file=sys.stderr)
        sys.exit(1)

    # 使用不会出现在提交信息中的分隔符，避免解析冲突
    sep = "<<<FIELD_SEP>>>"
    fmt = sep.join(["%h", "%s", "%an", "%ai"])

    log_args = ["log", f"--since={since}", f"--pretty=format:{fmt}"]
    if author:
        log_args.append(f"--author={author}")

    raw = run_git(log_args, cwd=str(repo_path))
    if not raw:
        return []

    commits = []
    for line in raw.splitlines():
        parts = line.split(sep)
        if len(parts) != 4:
            continue
        sha, subject, commit_author, datetime_str = parts

        # 获取该提交涉及的文件列表
        files_raw = run_git(
            ["show", "--name-only", "--pretty=format:", sha],
            cwd=str(repo_path),
        )
        files = [f for f in files_raw.splitlines() if f.strip()]

        commits.append({
            "sha": sha,
            "subject": subject,
            "author": commit_author,
            "datetime": datetime_str,
            "files_changed": files,
        })

    return commits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default="today 00:00",
        help="时间范围（git --since 语法）。默认：today 00:00",
    )
    parser.add_argument(
        "--author",
        default=None,
        help="按作者过滤。传 'me' 表示使用当前 git user.name",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="git 仓库路径。默认：当前目录",
    )
    args = parser.parse_args()

    # 把 --author=me 解析为当前 git 用户
    author = args.author
    if author == "me":
        author = run_git(["config", "user.name"], cwd=args.repo)

    commits = extract_commits(args.since, author, args.repo)
    json.dump(commits, sys.stdout, ensure_ascii=False, indent=2)
    print()  # 末尾补一个换行


if __name__ == "__main__":
    main()
