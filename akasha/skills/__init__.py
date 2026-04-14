"""
Skill 系统 — 可插拔的能力扩展。

核心理念: Skill 的灵魂是 skill.md（Markdown），Python 只是薄执行层。

加载流程:
  1. 扫描 skills/ 下所有子目录
  2. 找到 skill.md → 解析 frontmatter → 构造 SkillDef
  3. 动态 import executor.py → 获取 handler 方法
  4. 注册为 MCP tools
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SkillDef:
    """Skill 定义（从 skill.md frontmatter 解析）。"""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    skill_dir: Path = field(default_factory=Path)
    prompt: str = ""  # skill.md 完整内容


def discover_skills(skills_dir: Path) -> list[SkillDef]:
    """扫描 skills/ 下所有子目录，找到 skill.md → 解析 → 构造 SkillDef。

    Args:
        skills_dir: skills/ 目录路径

    Returns:
        SkillDef 列表
    """
    skills: list[SkillDef] = []

    if not skills_dir.exists():
        return skills

    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue

        skill_md = child / "skill.md"
        if not skill_md.exists():
            continue

        try:
            text = skill_md.read_text(encoding="utf-8")
            meta = _parse_skill_frontmatter(text)
            if not meta.get("name"):
                continue

            skills.append(
                SkillDef(
                    name=meta["name"],
                    description=meta.get("description", ""),
                    tools=meta.get("tools", []),
                    requires=meta.get("requires", []),
                    skill_dir=child,
                    prompt=text,
                )
            )
        except Exception as e:
            print(f"[skills] 加载 {child.name}/skill.md 失败: {e}")

    return skills


def load_executor(skill: SkillDef):
    """动态加载 Skill 的 executor 模块，返回 executor 实例。

    executor.py 必须定义 get_executor() 函数。
    """
    module_name = f"akasha.skills.{skill.name}.executor"
    module = importlib.import_module(module_name)
    return module.get_executor()


def _parse_skill_frontmatter(text: str) -> dict:
    """解析 skill.md 的 YAML frontmatter。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                pass
    return {}
