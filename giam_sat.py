"""Monitoring: log JSON từng dòng, metric Prometheus, và thống kê nhanh 200 hoá đơn gần nhất cho trang web.

Ba câu hỏi vận hành cần trả lời được:
  App có đang chạy đúng không?    tỉ lệ GHI SỔ, CẦN NGƯỜI XEM, CHẶN
  Có chậm không, chậm ở bước nào? thời gian từng bước, p50 và p95
  Tốn bao nhiêu tiền?             số lượt gọi AWS, $ đã tiêu, hạn mức còn lại
"""
import collections
import json
import threading
import time

import numpy as np
from prometheus_client import Counter, Histogram

HOA_DON = Counter("receipts_total", "Số hoá đơn đã xử lý", ["trang_thai", "nguon"])
BUOC_GIAY = Histogram("step_seconds", "Thời gian từng bước", ["buoc"], buckets=(.05, .1, .25, .5, 1, 2, 4, 8, 16))
AWS_GOI = Counter("aws_calls_total", "Số lượt gọi AWS", ["dich_vu", "ket_qua"])
AWS_USD = Counter("aws_cost_usd_total", "Tiền AWS đã tiêu, $")

_gan_day = collections.deque(maxlen=200)
_khoa = threading.Lock()


def log(su_kien, **du_lieu):
    """Một dòng JSON mỗi sự kiện, in ra terminal đang chạy server."""
    print(json.dumps({"luc": time.strftime("%Y-%m-%d %H:%M:%S"), "su_kien": su_kien, **du_lieu},
                     ensure_ascii=False, default=str), flush=True)


def ghi_buoc(buoc, giay):
    BUOC_GIAY.labels(buoc).observe(giay)


def ghi_aws(dich_vu, ok, usd=0.0):
    AWS_GOI.labels(dich_vu, "ok" if ok else "loi").inc()
    AWS_USD.inc(usd)


def ghi_loi(loi):
    """Lỗi không lường trước (model, ảnh lạ): vẫn phải hiện trên metric và log, không được im lặng."""
    HOA_DON.labels("LỖI", "-").inc()
    log("loi", loi=loi[:300])


def ghi_ket_qua(kq):
    """kq là dict KetQua của pipeline."""
    HOA_DON.labels(kq["trang_thai"], kq["nguon"] or "-").inc()
    with _khoa:
        _gan_day.append(kq)
    log("ket_qua", **{k: kq[k] for k in ("trang_thai", "nguon", "ly_do", "tong_cong", "giay", "chi_phi_usd",
                                         "loi_aws")})


def thong_ke():
    """Số liệu cho bảng monitoring trên trang web."""
    with _khoa:
        ds = list(_gan_day)
    if not ds:
        return {"so_hoa_don": 0}
    giay = [k["giay"] for k in ds]
    return {
        "so_hoa_don": len(ds),
        "trang_thai": dict(collections.Counter(k["trang_thai"] for k in ds)),
        "ti_le_fallback": round(sum(k["da_goi_aws"] for k in ds) / len(ds), 3),
        "giay_p50": round(float(np.percentile(giay, 50)), 2),
        "giay_p95": round(float(np.percentile(giay, 95)), 2),
        "chi_phi_usd": round(sum(k["chi_phi_usd"] for k in ds), 5),
    }
