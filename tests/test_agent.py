"""
测试 Agent — Phase 4。

覆盖:
- action 解析（从 LLM 响应中提取 JSON）
- Executor（调用 Vault 方法）
- Agent Loop（多轮 think → act → observe）
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from akasha.vault import Vault
from akasha.agent.loop import AgentLoop, AgentMessage
from akasha.agent.executor import Executor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """创建测试 Vault。"""
    vault_path = tmp_path / "vault"
    os.environ["AKASHA_VAULT_PATH"] = str(vault_path)
    os.environ["AKASHA_CHROMA_DIR"] = str(tmp_path / "chroma")
    os.environ["AKASHA_LLM_API_KEY"] = "test-key"
    os.environ["AKASHA_LLM_BASE_URL"] = "https://fake.api/v1"

    v = Vault(vault_path)
    v.init()

    docs = vault_path / "docs"
    note = docs / "raw" / "notes" / "test.md"
    note.write_text(
        """\
---
tags: [test]
title: Test Note
---

# Test Note

This is a test note about Agent Loop design patterns.
""",
        encoding="utf-8",
    )

    return v


@pytest.fixture
def mock_llm():
    """Mock LLM 客户端。"""
    llm = MagicMock()
    llm._client = MagicMock()
    llm._model = "test-model"
    return llm


# ---------------------------------------------------------------------------
# Action 解析
# ---------------------------------------------------------------------------


class TestParseAction:
    def test_parse_action_in_code_block(self):
        text = '我来搜索一下。\n\n```json\n{"action": "search", "params": {"query": "Agent Loop"}}\n```'
        result = AgentLoop._parse_action(text)
        assert result is not None
        action, params = result
        assert action == "search"
        assert params["query"] == "Agent Loop"

    def test_parse_action_inline(self):
        text = '让我搜索一下 {"action": "search", "params": {"query": "test"}}'
        result = AgentLoop._parse_action(text)
        assert result is not None
        assert result[0] == "search"

    def test_parse_no_action(self):
        text = "搜索完成，找到了 3 条相关内容。以下是结果摘要..."
        result = AgentLoop._parse_action(text)
        assert result is None

    def test_parse_action_no_params(self):
        text = '```json\n{"action": "list_notes"}\n```'
        result = AgentLoop._parse_action(text)
        assert result is not None
        assert result[0] == "list_notes"
        assert result[1] == {}

    def test_parse_action_nested_params(self):
        text = '```json\n{"action": "save_page", "params": {"title": "My Page", "content": "Hello", "category": "synthesis"}}\n```'
        result = AgentLoop._parse_action(text)
        assert result is not None
        assert result[0] == "save_page"
        assert result[1]["title"] == "My Page"

    def test_parse_invalid_json(self):
        text = "```json\n{broken json}\n```"
        result = AgentLoop._parse_action(text)
        assert result is None


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class TestExecutor:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_search(self, vault: Vault):
        executor = Executor(vault)
        result = await executor.execute("search", {"query": "Agent Loop"})
        assert isinstance(result, str)
        assert "找到" in result or "没有找到" in result or "为空" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_read(self, vault: Vault):
        executor = Executor(vault)
        result = await executor.execute("read", {"file_path": "raw/notes/test.md"})
        assert "Test Note" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_list_notes(self, vault: Vault):
        executor = Executor(vault)
        result = await executor.execute("list_notes")
        assert isinstance(result, str)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_lint(self, vault: Vault):
        executor = Executor(vault)
        result = await executor.execute("lint")
        assert "通过" in result or "问题" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unknown_tool(self, vault: Vault):
        executor = Executor(vault)
        result = await executor.execute("nonexistent_tool")
        assert "未知工具" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_error_handling(self, vault: Vault):
        executor = Executor(vault)
        result = await executor.execute("read", {"file_path": "nonexistent.md"})
        assert "不存在" in result

    def test_available_tools(self, vault: Vault):
        executor = Executor(vault)
        tools = executor.get_available_tools()
        assert "search" in tools
        assert "ingest" in tools
        assert "lint" in tools


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------


class TestAgentLoop:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_single_step_final_answer(self, vault: Vault, mock_llm):
        """LLM 直接回复最终答案，不调用工具。"""
        agent = AgentLoop(vault, llm_client=mock_llm)

        # Mock LLM 直接返回最终回复
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "知识库里目前没有什么特别的内容。"
        mock_llm._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await agent.run("知识库里有什么？")
        assert "知识库" in result
        assert len(agent.steps) == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_tool_call_then_answer(self, vault: Vault, mock_llm):
        """LLM 先调用工具，再返回最终答案。"""
        agent = AgentLoop(vault, llm_client=mock_llm)

        # 第一次调用: LLM 决定搜索
        resp1 = MagicMock()
        resp1.choices = [MagicMock()]
        resp1.choices[
            0
        ].message.content = '让我搜索一下。\n\n```json\n{"action": "search", "params": {"query": "Agent Loop"}}\n```'

        # 第二次调用: LLM 看到搜索结果后给出最终回复
        resp2 = MagicMock()
        resp2.choices = [MagicMock()]
        resp2.choices[0].message.content = "搜索完成。找到了关于 Agent Loop 的内容。"

        mock_llm._client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

        result = await agent.run("搜一下 Agent Loop")
        assert "搜索完成" in result
        assert len(agent.steps) == 2  # search + final answer
        assert agent.steps[0].action == "search"
        assert agent.steps[0].result is not None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_multi_step(self, vault: Vault, mock_llm):
        """LLM 多步执行。"""
        agent = AgentLoop(vault, llm_client=mock_llm)

        # Step 1: 列出笔记
        resp1 = MagicMock()
        resp1.choices = [MagicMock()]
        resp1.choices[0].message.content = '```json\n{"action": "list_notes"}\n```'

        # Step 2: 读取某个文件
        resp2 = MagicMock()
        resp2.choices = [MagicMock()]
        resp2.choices[
            0
        ].message.content = '```json\n{"action": "read", "params": {"file_path": "raw/notes/test.md"}}\n```'

        # Step 3: 最终回复
        resp3 = MagicMock()
        resp3.choices = [MagicMock()]
        resp3.choices[
            0
        ].message.content = "我看了 test.md，这是一篇关于 Agent Loop 的笔记。"

        mock_llm._client.chat.completions.create = AsyncMock(
            side_effect=[resp1, resp2, resp3]
        )

        result = await agent.run("看看知识库里有什么笔记，读一下最新的")
        assert len(agent.steps) == 3
        assert agent.steps[0].action == "list_notes"
        assert agent.steps[1].action == "read"
        assert agent.steps[2].action is None  # 最终回复

    @pytest.mark.asyncio(loop_scope="function")
    async def test_max_steps_limit(self, vault: Vault, mock_llm):
        """超过最大步数应该停止。"""
        agent = AgentLoop(vault, llm_client=mock_llm)

        # LLM 一直返回工具调用
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '```json\n{"action": "list_notes"}\n```'

        mock_llm._client.chat.completions.create = AsyncMock(return_value=resp)

        result = await agent.run("做点什么")
        assert "停止" in result

    def test_system_prompt_includes_schema(self, vault: Vault, mock_llm):
        """system prompt 应该包含 schema 内容。"""
        agent = AgentLoop(vault, llm_client=mock_llm)
        assert "Akasha" in agent._system_prompt
        assert "Schema" in agent._system_prompt or "schema" in agent._system_prompt


# ---------------------------------------------------------------------------
# Vault.ask 集成
# ---------------------------------------------------------------------------


class TestVaultAsk:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_vault_ask(self, vault: Vault, mock_llm):
        """vault.ask() 应该能正常调用 Agent。"""
        # Mock LLMClient 构造
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "你好，知识库目前有一些笔记。"

        with patch("akasha.agent.loop.AgentLoop") as MockAgent:
            instance = MockAgent.return_value
            instance.run = AsyncMock(return_value="你好，知识库目前有一些笔记。")

            result = await vault.ask("你好")
            assert "你好" in result or "知识库" in result
