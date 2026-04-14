"""
配置模块 — 集中管理所有配置项。

优先级: 环境变量 > 默认值

Vault 目录结构（由 AKASHA_VAULT_PATH 指定，默认 ~/akasha）:
  ~/akasha/                    ← vault 根目录
  ├── mkdocs.yml               ← 站点配置（动态生成）
  ├── docs/                    ← 所有 Markdown 内容（mkdocs docs_dir）
  │   ├── schema.md
  │   ├── index.md
  │   ├── log.md
  │   ├── raw/                 ← 原始素材（你写的，LLM 只读）
  │   │   ├── analysis/
  │   │   ├── notes/
  │   │   └── articles/
  │   └── wiki/                ← LLM 维护的 wiki 页面
  │       ├── concepts/
  │       ├── entities/
  │       ├── comparisons/
  │       └── synthesis/
  └── site/                    ← 站点构建产物（mkdocs site_dir）
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_VAULT = str(Path.home() / "akasha")


@dataclass
class Config:
    """Akasha 知识库配置。"""

    # ── Vault 根路径 ──
    vault_path: Path = field(
        default_factory=lambda: Path(os.getenv("AKASHA_VAULT_PATH", _DEFAULT_VAULT))
    )

    # ── ChromaDB ──
    chroma_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("AKASHA_CHROMA_DIR", Path.home() / ".akasha" / "chroma")
        )
    )
    collection_name: str = "akasha"

    # ── LLM 配置（用于 ingest / save_as_page / lint_wiki / Agent）──
    llm_provider: str = field(
        default_factory=lambda: os.getenv("AKASHA_LLM_PROVIDER", "openai")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("AKASHA_LLM_API_KEY", "")
    )
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("AKASHA_LLM_BASE_URL", "")
    )
    llm_model: str = field(default_factory=lambda: os.getenv("AKASHA_LLM_MODEL", ""))

    # ── 搜索 ──
    default_top_k: int = field(
        default_factory=lambda: int(os.getenv("AKASHA_DEFAULT_TOP_K", "5"))
    )

    # ── 索引 ──
    skip_dirs: set[str] = field(
        default_factory=lambda: {
            ".obsidian",
            ".git",
            "node_modules",
            "__pycache__",
            "site",
            ".venv",
        }
    )
    min_chunk_length: int = 20
    max_chunk_store_length: int = 8000
    batch_size: int = 100

    # ── 展示 ──
    max_display_length: int = 500
    max_read_length: int = 10000

    # ── 派生路径（所有内容在 docs/ 下）──
    @property
    def docs_dir(self) -> Path:
        return self.vault_path / "docs"

    @property
    def site_dir(self) -> Path:
        return self.vault_path / "site"

    @property
    def raw_dir(self) -> Path:
        return self.docs_dir / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.docs_dir / "wiki"

    @property
    def schema_path(self) -> Path:
        return self.docs_dir / "schema.md"

    @property
    def index_path(self) -> Path:
        return self.docs_dir / "index.md"

    @property
    def log_path(self) -> Path:
        return self.docs_dir / "log.md"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def llm_base_url_resolved(self) -> str:
        """返回实际使用的 base_url（未设置时按 provider 给默认值）。"""
        if self.llm_base_url:
            return self.llm_base_url
        defaults = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
        }
        return defaults.get(self.llm_provider, "https://api.openai.com/v1")

    @property
    def llm_model_resolved(self) -> str:
        """返回实际使用的 model 名称（未设置时按 provider 给默认值）。"""
        if self.llm_model:
            return self.llm_model
        defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-20250514",
        }
        return defaults.get(self.llm_provider, "gpt-4o")


def load_config() -> Config:
    return Config()
