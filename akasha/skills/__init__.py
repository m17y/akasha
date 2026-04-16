"""
Skill 系统 — 可插拔的能力扩展。

核心理念: Skill 的灵魂是 skill.md（Markdown），Python 只是薄执行层。
skill.md 同时也是 Agent 的能力说明书。

加载流程:
  1. 扫描 skills/ 下所有子目录
  2. 找到 skill.md → 解析 frontmatter → 构造 SkillDef
  3. 动态 import executor.py → 获取 handler 方法
  4. 构造 SkillAction 列表（tool_name → handler）
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml


@dataclass
class SkillDef:
    """Skill 定义（从 skill.md frontmatter 解析）。"""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    skill_dir: Path = field(default_factory=Path)
    prompt: str = ""  # skill.md 完整内容（给 Agent 读）


@dataclass
class SkillAction:
    """一个可执行的 skill 操作。"""

    tool_name: str  # MCP tool 名，如 video_download
    skill_name: str  # 所属 skill 名，如 video
    description: str  # 工具描述（从 skill.md 或 executor 提取）
    handler: Callable  # 实际执行函数
    skill_def: SkillDef  # 完整 skill 定义


class SkillRegistry:
    """Skill 注册表 — 发现、加载、管理所有 skill。"""

    def __init__(self):
        self.skills: list[SkillDef] = []
        self.actions: dict[str, SkillAction] = {}  # tool_name → SkillAction

    def discover_and_load(self, skills_dir: Path | None = None) -> int:
        """扫描 skills/ 目录，发现并加载所有 skill。

        Args:
            skills_dir: skills/ 目录路径。None 则使用默认路径。

        Returns:
            成功注册的 action 数量
        """
        if skills_dir is None:
            skills_dir = Path(__file__).parent

        self.skills = _discover_skills(skills_dir)
        registered = 0

        for skill in self.skills:
            try:
                executor = _load_executor(skill)
            except Exception as e:
                print(f"[skills] {skill.name} 加载失败: {e}")
                continue

            # 自动映射: tool_name → executor 方法
            # 规则: video_download → executor.download
            #       web_clip_save → executor.save
            #       media_transcribe → executor.transcribe
            for tool_name in skill.tools:
                method_name = tool_name.replace(f"{skill.name}_", "")
                handler = getattr(executor, method_name, None)

                if handler is None:
                    print(
                        f"[skills] {skill.name}: "
                        f"方法 {method_name} 不存在，跳过 {tool_name}"
                    )
                    continue

                self.actions[tool_name] = SkillAction(
                    tool_name=tool_name,
                    skill_name=skill.name,
                    description=f"{skill.description} — {method_name}",
                    handler=handler,
                    skill_def=skill,
                )
                registered += 1

        return registered

    def get_action(self, tool_name: str) -> SkillAction | None:
        """获取指定 tool 的 action。"""
        return self.actions.get(tool_name)

    def get_all_actions(self) -> list[SkillAction]:
        """获取所有已注册的 action。"""
        return list(self.actions.values())

    def get_skill_prompts(self) -> dict[str, str]:
        """获取所有 skill 的 prompt（skill.md 内容），供 Agent 使用。

        Returns:
            {skill_name: skill.md 完整内容}
        """
        return {skill.name: skill.prompt for skill in self.skills}

    def get_skill(self, name: str) -> SkillDef | None:
        """获取指定 skill 的定义。"""
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None


# ---------------------------------------------------------------------------
# 内部函数
# ---------------------------------------------------------------------------


def _discover_skills(skills_dir: Path) -> list[SkillDef]:
    """扫描 skills/ 下所有子目录，解析 skill.md。"""
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
            meta = _parse_frontmatter(text)
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


def _load_executor(skill: SkillDef):
    """动态加载 executor 模块，返回 executor 实例。"""
    module_name = f"akasha.skills.{skill.name}.executor"
    module = importlib.import_module(module_name)
    return module.get_executor()


def _parse_frontmatter(text: str) -> dict:
    """解析 YAML frontmatter。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                pass
    return {}
