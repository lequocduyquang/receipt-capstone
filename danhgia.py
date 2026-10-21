"""Eval: chạy cả chuỗi trên 30 hoá đơn có đáp án, ở 3 dạng ảnh, rồi đếm.

  goc   ảnh gốc
  che   dòng TỔNG CỘNG bị tô trắng (bài kiểm của Buổi 22: Nova + harness để lọt 8/10)
  kho   ảnh chất lượng thấp: thu nhỏ còn 60%, nén JPEG 30 (giống ảnh gửi qua chat), PaddleOCR bắt đầu đọc sai

"Ghi sổ đúng" là tổng tiền, ngày và danh mục đều đúng. "Sai mà lọt" là ghi sổ nhưng sai, loại lỗi đắt nhất.

Chạy:
  python danhgia.py                       30 hoá đơn × 3 dạng, không gọi AWS (miễn phí)
  python danhgia.py --n 10 --dang che     10 hoá đơn, chỉ dạng che
  python danhgia.py --aws                 bật fallback Textract và Nova Lite (cần key AWS, khoảng $0,06 cho 90 ảnh)
  python danhgia.py --ray 4               chạy song song 4 bản bằng Ray, mỗi bản tải model một lần
Mỗi ảnh một dòng trong danhgia.jsonl để mở ra xem lại.
"""
import argparse
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

THU_MUC = Path(__file__).parent / "data" / "receipts"
NHAN = json.loads((THU_MUC / "labels.json").read_text())
TI_LE, CHAT_LUONG = 0.6, 30   # mức "kho": nặng hơn (35%, JPEG 25) thì chính Nova cũng đọc sai, chỉ còn cách chuyển người


def tao_anh(ten, dang):
    img = Image.open(THU_MUC / ten).convert("RGB")
    if dang == "che":   # tô trắng chữ "TỔNG CỘNG" và con số tổng gần nó nhất, theo đúng khung nghiêng trong đáp án
        import logic
        cac_dong, tong = NHAN[ten]["lines"], NHAN[ten]["data"]["tong_cong"]
        y = lambda d: sum(p[1] for p in d["poly"]) / 4
        nhan = next(d for d in cac_dong if "TỔNG" in d["text"])
        so = min((d for d in cac_dong if tong in logic.cac_so(d["text"])), key=lambda d: abs(y(d) - y(nhan)))
        for d in (nhan, so):
            ImageDraw.Draw(img).polygon([tuple(p) for p in d["poly"]], fill="white", outline="white", width=10)
    elif dang == "kho":
        img = img.resize((int(img.width * TI_LE), int(img.height * TI_LE)))
        b = io.BytesIO()
        img.save(b, "JPEG", quality=CHAT_LUONG)
        img = Image.open(b).convert("RGB")
    return img


def cham(ten, kq):
    """Xếp một kết quả vào một trong 4 nhóm."""
    import logic
    if kq["trang_thai"] == logic.CHAN:
        return "bị chặn"
    if kq["trang_thai"] == logic.CAN_NGUOI_XEM:
        return "chuyển người"
    d = NHAN[ten]["data"]
    dung = (kq["tong_cong"], kq["ngay"], kq["danh_muc"]) == (d["tong_cong"], d["ngay"], logic.gan_danh_muc(d["cua_hang"]))
    return "ghi sổ đúng" if dung else "sai mà lọt"


class ChayMot:
    """Một bản chạy eval. Dùng chung cho vòng for và cho Ray (mỗi actor Ray tạo một bản, tải model một lần)."""

    def __init__(self, dung_aws):
        import sys
        sys.path.insert(0, str(THU_MUC.parent.parent))   # actor Ray là process riêng, phải tự tìm thấy code của app
        import aws
        import giam_sat
        import mo_hinh
        log_goc = giam_sat.log   # eval in một bảng ở cuối: chỉ giữ log lỗi, bỏ log từng ảnh
        giam_sat.log = lambda su_kien, **kv: su_kien.startswith("loi") and log_goc(su_kien, **kv)
        mo_hinh.tai_model()
        self.cho_phep = dung_aws and aws.co_key()

    def __call__(self, viec):
        import pipeline
        kq = pipeline.xu_ly(tao_anh(viec["ten"], viec["dang"]), cho_phep_aws=self.cho_phep)
        return {**viec, "nhom": cham(viec["ten"], kq), **{k: kq[k] for k in
                ("trang_thai", "nguon", "ly_do", "tong_cong", "giay", "chi_phi_usd", "da_goi_aws", "loi_aws")}}


def bao_cao(ket_qua, giay):
    print(f"\n{len(ket_qua)} ảnh trong {giay:.0f} giây")
    print(f"{'dạng':<6}{'ghi sổ đúng':>13}{'sai mà lọt':>12}{'chuyển người':>14}{'bị chặn':>9}{'gọi AWS':>9}"
          f"{'lỗi AWS':>9}{'p50 s':>8}{'p95 s':>8}{'$':>9}")
    for dang in dict.fromkeys(k["dang"] for k in ket_qua):
        ds = [k for k in ket_qua if k["dang"] == dang]
        dem = {n: sum(k["nhom"] == n for k in ds) for n in ("ghi sổ đúng", "sai mà lọt", "chuyển người", "bị chặn")}
        giay_moi_anh = [k["giay"] for k in ds]
        print(f"{dang:<6}{dem['ghi sổ đúng']:>13}{dem['sai mà lọt']:>12}{dem['chuyển người']:>14}{dem['bị chặn']:>9}"
              f"{sum(k['da_goi_aws'] for k in ds):>9}{sum(k['loi_aws'] for k in ds):>9}{np.percentile(giay_moi_anh, 50):>8.1f}"
              f"{np.percentile(giay_moi_anh, 95):>8.1f}{sum(k['chi_phi_usd'] for k in ds):>9.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--dang", default="goc,che,kho")
    p.add_argument("--aws", action="store_true", help="bật fallback Textract và Nova Lite")
    p.add_argument("--ray", type=int, default=0, help="số bản chạy song song bằng Ray, 0 là vòng for")
    a = p.parse_args()

    viec = [{"ten": t, "dang": d} for d in a.dang.split(",") for t in sorted(NHAN)[:a.n]]
    t = time.time()
    if a.ray:
        import ray
        ray.init(log_to_driver=False)
        ds = ray.data.from_items(viec, override_num_blocks=len(viec))   # mỗi ảnh một block, chia đều cho các actor
        ket_qua = ds.map(ChayMot, fn_constructor_kwargs={"dung_aws": a.aws}, concurrency=a.ray, num_cpus=1).take_all()
        ket_qua.sort(key=lambda k: (a.dang.split(",").index(k["dang"]), k["ten"]))
    else:
        chay = ChayMot(a.aws)
        ket_qua = [chay(v) for v in viec]
    bao_cao(ket_qua, time.time() - t)
    (THU_MUC.parent.parent / "danhgia.jsonl").write_text("\n".join(json.dumps(k, ensure_ascii=False) for k in ket_qua) + "\n")
