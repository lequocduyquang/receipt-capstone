"""Bản học viên phải xoá đúng 5 lời giải và vẫn là code Python chạy được."""
import ast
from pathlib import Path

from ban_hoc_vien import xoa_loi_giai


def test_xoa_dung_5_loi_giai():
    code = xoa_loi_giai((Path(__file__).parent.parent / "logic.py").read_text())
    ast.parse(code)
    assert "lời giải ---" not in code
    assert [f'NotImplementedError("TODO {i}")' in code for i in range(1, 6)] == [True] * 5
