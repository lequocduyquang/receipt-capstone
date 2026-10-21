"""Tạo bản học viên từ bản lời giải: chép cả thư mục, thay lời giải trong logic.py bằng raise NotImplementedError.

Chỉ sửa lời giải ở một chỗ (nhánh main), bản học viên luôn sinh lại được, không bao giờ lệch nhau.
    git worktree add ../receipt-capstone-dev dev     một lần
    python ban_hoc_vien.py                           ghi đè vào worktree đó (giữ nguyên .git), rồi commit ở đó
"""
import re
import shutil
import sys
from pathlib import Path

NGUON = Path(__file__).parent
BO_QUA = shutil.ignore_patterns(".git", "capenv", "__pycache__", ".pytest_cache", ".env", "danhgia.jsonl",
                                "ban_hoc_vien.py", "test_ban_hoc_vien.py")


def xoa_loi_giai(code):
    """Mỗi khối giữa '# --- lời giải ---' và '# --- hết lời giải ---' thành một dòng raise, giữ nguyên thụt lề."""
    so = iter(range(1, 100))
    return re.sub(r"( *)# --- lời giải ---\n.*?# --- hết lời giải ---\n",
                  lambda m: f'{m[1]}raise NotImplementedError("TODO {next(so)}")\n', code, flags=re.S)


if __name__ == "__main__":
    DICH = Path(sys.argv[1]) if len(sys.argv) > 1 else NGUON.parent / "receipt-capstone-dev"
    assert DICH.resolve() != NGUON.resolve(), "thư mục đích không được là thư mục lời giải"
    DICH.mkdir(exist_ok=True)
    for f in DICH.iterdir():   # xoá bản cũ nhưng giữ .git (worktree) và môi trường Python
        if f.name in (".git", "capenv"):
            continue
        if f.is_dir():
            shutil.rmtree(f)
        else:
            f.unlink()
    shutil.copytree(NGUON, DICH, ignore=BO_QUA, dirs_exist_ok=True)
    logic = xoa_loi_giai((NGUON / "logic.py").read_text())
    assert "lời giải ---" not in logic and logic.count("NotImplementedError") == 5
    (DICH / "logic.py").write_text(logic)
    print(f"Đã tạo {DICH}. Chạy pytest trong đó: test phần có sẵn qua, test TODO báo NotImplementedError.")
