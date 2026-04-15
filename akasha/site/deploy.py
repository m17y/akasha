"""站点部署到 GitHub Pages。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _deploy(cfg, yml_path: Path):
    """构建站点并自动发布到 GitHub Pages。"""
    from datetime import datetime

    site_repo = cfg.site_repo
    if not site_repo:
        print("错误: 未配置 AKASHA_SITE_REPO")
        print("请设置环境变量，例如:")
        print('  export AKASHA_SITE_REPO="https://github.com/user/user.github.io.git"')
        sys.exit(1)

    site_dir = cfg.site_dir

    # 1. 构建
    print(">>> 构建站点...")
    mkdocs_cmd = [sys.executable, "-m", "mkdocs", "build", "-f", str(yml_path)]
    subprocess.run(mkdocs_cmd, check=True)

    # 2. 初始化 git（如果还没有）
    git_dir = site_dir / ".git"
    if not git_dir.exists():
        print(">>> 初始化 git...")
        subprocess.run(["git", "init"], cwd=site_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", site_repo],
            cwd=site_dir,
            check=True,
        )
    else:
        # 确保 remote 地址正确
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=site_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != site_repo:
            subprocess.run(
                ["git", "remote", "set-url", "origin", site_repo],
                cwd=site_dir,
            )

    # 3. 提交并推送
    print(">>> 提交并推送...")
    subprocess.run(["git", "add", "."], cwd=site_dir, check=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = subprocess.run(
        ["git", "commit", "-m", f"deploy wiki {ts}"],
        cwd=site_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "nothing to commit" in result.stdout:
        print(">>> 没有变更，跳过推送")
        return

    subprocess.run(
        ["git", "push", "-u", "origin", "main", "--force"],
        cwd=site_dir,
        check=True,
    )
    print(f">>> 部署完成!")
