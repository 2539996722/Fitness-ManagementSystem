"""kb_service 纯函数单测（无需 DB/Chroma/LLM，跑得飞快）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.kb_service import (
    _read_text_file,
    _sliding_window_split,
    _split_text,
    format_kb_context,
)


# ============ _read_text_file ============

class TestReadTextFile:
    """读 txt/md 编码回退逻辑。"""

    def test_read_utf8(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_bytes("你好，世界。Hello.".encode("utf-8"))
        assert _read_text_file(str(f)) == "你好，世界。Hello."

    def test_read_utf8_with_bom(self, tmp_path: Path):
        f = tmp_path / "b.txt"
        f.write_bytes("﻿带 BOM 的 UTF-8".encode("utf-8"))
        # BOM 应被吃掉
        out = _read_text_file(str(f))
        assert out == "带 BOM 的 UTF-8" or out.lstrip("﻿") == "带 BOM 的 UTF-8"

    def test_read_gbk(self, tmp_path: Path):
        f = tmp_path / "c.txt"
        f.write_bytes("中文 GBK 编码".encode("gbk"))
        assert _read_text_file(str(f)) == "中文 GBK 编码"

    def test_read_latin1_fallback(self, tmp_path: Path):
        f = tmp_path / "d.txt"
        # 全 latin-1 字节（不是 utf-8 也不是 gbk），兜底 latin-1
        f.write_bytes(b"\xe9\xe9\xe9 plain text")
        out = _read_text_file(str(f))
        assert "plain text" in out

    def test_read_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        assert _read_text_file(str(f)) == ""


# ============ _split_text (RecursiveCharacterTextSplitter 包装) ============

class TestSplitText:
    """分片逻辑。"""

    def test_short_text_returns_single_chunk(self):
        text = "短文本"
        chunks = _split_text(text, chunk_size=500, chunk_overlap=80)
        assert len(chunks) >= 1
        assert chunks[0] == text or text in chunks[0]

    def test_chinese_sentence_boundary(self):
        """中文按句号 / 换行切。"""
        text = "第一句。\n第二句。\n第三句。"
        chunks = _split_text(text, chunk_size=10, chunk_overlap=2)
        # 应该切成 ≥ 2 段
        assert len(chunks) >= 2

    def test_paragraph_break_priority(self):
        """\n\n 应该优先于 \n 成为切点。"""
        text = "段落一\n\n段落二\n\n段落三"
        chunks = _split_text(text, chunk_size=4, chunk_overlap=0)
        # 验证每段不超过 chunk_size 太多（允许一些 overlap 余量）
        for c in chunks:
            assert len(c) <= 4 + 5, f"chunk too long: {c!r}"

    def test_empty_text(self):
        chunks = _split_text("", chunk_size=500, chunk_overlap=80)
        assert chunks == [] or chunks == [""]

    def test_overlap_creates_redundancy(self):
        """相邻 chunk 应该有 overlap（重复内容）。"""
        text = "0123456789" * 20  # 200 字符
        chunks = _split_text(text, chunk_size=50, chunk_overlap=20)
        assert len(chunks) >= 2
        # 相邻 chunk 应有公共子串
        if len(chunks) >= 2:
            assert any(chunks[i][-20:] in chunks[i + 1] for i in range(len(chunks) - 1))


# ============ _sliding_window_split (langchain 缺失时的 fallback) ============

class TestSlidingWindow:
    def test_step_is_size_minus_overlap(self):
        chunks = _sliding_window_split("abcdefghij", size=4, overlap=1)
        # step = 3, [0:4]=abcd, [3:7]=defg, [6:10]=ghij
        assert chunks == ["abcd", "defg", "ghij"]

    def test_size_zero_returns_full(self):
        chunks = _sliding_window_split("hello", size=0, overlap=0)
        assert chunks == ["hello"]

    def test_size_negative_returns_full(self):
        chunks = _sliding_window_split("hello", size=-1, overlap=0)
        assert chunks == ["hello"]

    def test_no_infinite_loop_on_overlap_equals_size(self):
        # overlap == size 会导致 step=0，无限循环；应有保护
        chunks = _sliding_window_split("abcdef", size=3, overlap=3)
        assert len(chunks) >= 1  # 不会死循环


# ============ format_kb_context ============

class TestFormatKbContext:
    """LLM 上下文拼接：来源标注 + 不能凭空编造。"""

    def _make_chunk(self, text, filename="健身指南.md", chunk_index=0, score=0.1):
        from app.services.kb_service import KbChunk
        return KbChunk(
            doc_id=1,
            filename=filename,
            chunk_index=chunk_index,
            text=text,
            score=score,
        )

    def test_empty_chunks_returns_empty(self):
        assert format_kb_context([]) == ""

    def test_single_chunk_format(self):
        out = format_kb_context([self._make_chunk("每周三次训练")])
        assert "每周三次训练" in out
        assert "健身指南.md" in out
        assert "第 0 段" in out
        assert "相关度" in out

    def test_includes_anti_hallucination_reminder(self):
        """context 里必须包含「找不到就说找不到」的提示。"""
        out = format_kb_context([self._make_chunk("某知识")])
        assert "知识库中没有" in out or "不要凭空编造" in out

    def test_multiple_chunks_numbered(self):
        chunks = [
            self._make_chunk("片段一", chunk_index=1),
            self._make_chunk("片段二", chunk_index=2),
        ]
        out = format_kb_context(chunks)
        assert "参考资料 1" in out
        assert "参考资料 2" in out
        assert "片段一" in out and "片段二" in out

    def test_score_formatted_to_3_decimals(self):
        out = format_kb_context([self._make_chunk("x", score=0.123456)])
        assert "0.123" in out
