"""
冒烟测试 — auto-improve 每轮必跑。

不需要 LLM，不需要网络，纯本地验证核心模块能正常导入和基本运行。
"""

import ast
from pathlib import Path


PROJECT_DIR = Path(__file__).parent.parent
AKASHA_DIR = PROJECT_DIR / "akasha"


class TestSyntax:
    """所有 Python 文件语法正确。"""

    def test_all_python_files_parse(self):
        errors = []
        for py_file in AKASHA_DIR.rglob("*.py"):
            try:
                ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as e:
                errors.append(f"{py_file.relative_to(PROJECT_DIR)}: {e}")
        assert not errors, f"Syntax errors:\n" + "\n".join(errors)


class TestImports:
    """核心模块能正常导入。"""

    def test_import_config(self):
        from akasha.config import Config

    def test_import_memory(self):
        from akasha.memory import Memory

    def test_import_vault(self):
        from akasha.vault import Vault

    def test_import_llm(self):
        from akasha.llm import LLMClient

    def test_import_agent_loop(self):
        from akasha.agent.loop import AgentLoop

    def test_import_agent_executor(self):
        from akasha.agent.executor import Executor

    def test_import_site(self):
        from akasha.site import main

    def test_import_skills(self):
        from akasha.skills import SkillRegistry


class TestConfig:
    """配置加载不崩溃。"""

    def test_default_config(self):
        from akasha.config import Config

        # Config 有默认值，不传参不应崩溃
        c = Config()
        assert c.vault_path is not None
        assert c.docs_dir is not None

    def test_docs_dir_under_vault(self):
        from akasha.config import Config

        c = Config()
        assert str(c.docs_dir).startswith(str(c.vault_path))


class TestMemory:
    """Memory 基本读写。"""

    def test_memory_init(self, tmp_path):
        from akasha.memory import Memory

        m = Memory(tmp_path)
        assert (tmp_path / ".memory").exists()

    def test_remember_and_read(self, tmp_path):
        from akasha.memory import Memory

        m = Memory(tmp_path)
        m.remember("test info", user_id="u1")
        ctx = m.get_context(user_id="u1")
        assert "test info" in ctx

    def test_global_memory(self, tmp_path):
        from akasha.memory import Memory

        m = Memory(tmp_path)
        m.remember("global info")
        ctx = m.get_context()
        assert "global info" in ctx


class TestJunkFilter:
    """垃圾概念过滤。"""

    def test_filter_platforms(self):
        from akasha.vault import _is_junk_concept

        assert _is_junk_concept("百度")
        assert _is_junk_concept("CSDN")
        assert _is_junk_concept("博客园")

    def test_filter_mixed_lang(self):
        from akasha.vault import _is_junk_concept

        assert _is_junk_concept("AWQ量化")
        assert _is_junk_concept("Agent架构")

    def test_keep_valid_concepts(self):
        from akasha.vault import _is_junk_concept

        assert not _is_junk_concept("Agent")
        assert not _is_junk_concept("RAG")
        assert not _is_junk_concept("量化")

    def test_filter_short(self):
        from akasha.vault import _is_junk_concept

        assert _is_junk_concept("a")

    def test_filter_url(self):
        from akasha.vault import _is_junk_concept

        assert _is_junk_concept("https://example.com")
