"""Ráp cả chuỗi: ảnh hoá đơn vào, một dòng sổ chi tiêu (hoặc phiếu chuyển người) ra.

  1. Cổng vào    độ nét, SigLIP 2 (ViT); SigLIP không chắc thì hỏi Nova (VQA tầng 2)
  2. Đọc chữ     PaddleOCR tìm khung (Buổi 20) và đọc chữ (Buổi 21), miễn phí
  3. Trích       tên quán, ngày, tổng tiền, danh mục; sensor cộng tiền
  4. Fallback    sensor lỗi hoặc đọc không tự tin: Textract và Nova Lite đọc lại, kiểm bằng sensor độc lập
  5. Cổng duyệt  có một nguồn qua sensor thì ghi sổ, không thì chuyển người
Các quyết định nằm trong logic.py. File này gọi model theo thứ tự, đo giờ và ghi monitoring.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import aws
import giam_sat
import logic
import mo_hinh

CAU_HOI_VQA = "Is this a photo of a receipt or an invoice?"


@contextmanager
def _buoc(cac_buoc, ma, ten):
    """Đo giờ một bước. ma là tên ngắn cho metric (dễ truy vấn), ten là tên đầy đủ hiện trên trang web."""
    muc = {"ma": ma, "ten": ten, "chi_tiet": ""}
    cac_buoc.append(muc)
    t = time.perf_counter()
    try:
        yield muc
    finally:
        muc["giay"] = round(time.perf_counter() - t, 3)
        giam_sat.ghi_buoc(ma, muc["giay"])


def _goi_aws(dich_vu, ham, *args):
    """Gọi một hàm của aws.py, ghi metric. Lỗi mạng hay hết quota thì trả về (None, 0) để harness tự chuyển người."""
    try:
        ket_qua, usd = ham(*args)
        giam_sat.ghi_aws(dich_vu, True, usd)
        return ket_qua, usd
    except Exception as e:   # botocore ClientError, timeout, throttling...
        giam_sat.ghi_aws(dich_vu, False)
        giam_sat.log("loi_aws", dich_vu=dich_vu, loi=str(e)[:200])
        return None, 0.0


def xu_ly(img, cho_phep_aws=False):
    """img: ảnh PIL. cho_phep_aws: có được gọi AWS không (server truyền vào aws.co_key())."""
    t0 = time.perf_counter()
    kq = {"trang_thai": logic.CHAN, "nguon": "", "ly_do": "", "cua_hang": None, "ngay": None, "tong_cong": None,
          "danh_muc": None, "diem_hoa_don": None, "do_net": None, "diem_ocr": None,
          "da_goi_aws": False, "loi_aws": False, "chi_phi_usd": 0.0, "buoc": []}
    cac_buoc = kq["buoc"]

    def xong():
        kq["giay"] = round(time.perf_counter() - t0, 3)
        kq["chi_phi_usd"] = round(kq["chi_phi_usd"], 6)
        giam_sat.ghi_ket_qua(kq)
        return kq

    # 1. Cổng vào
    with _buoc(cac_buoc, "cong_vao", "1. Cổng vào: độ nét, SigLIP 2") as b:
        img = mo_hinh.chuan_hoa(img)
        kq["do_net"], kq["diem_hoa_don"] = round(mo_hinh.do_net(img)), round(mo_hinh.diem_hoa_don(img), 3)
        quyet_dinh, ly_do = logic.quyet_cong_vao(kq["do_net"], kq["diem_hoa_don"])
        b["chi_tiet"] = f"độ nét {kq['do_net']}, điểm hoá đơn {kq['diem_hoa_don']}: {quyet_dinh}"
    if quyet_dinh == "HOI_VLM":
        with _buoc(cac_buoc, "vqa_nova", "1b. VQA tầng 2: hỏi Nova Lite") as b:
            la_hoa_don = None
            if cho_phep_aws and aws.han_muc.xin():
                kq["da_goi_aws"] = True
                la_hoa_don, usd = _goi_aws("nova_vqa", aws.hoi_nova, img, CAU_HOI_VQA)
                kq["chi_phi_usd"] += usd
                kq["loi_aws"] = la_hoa_don is None
            if la_hoa_don is True:
                quyet_dinh, ly_do = "QUA", ""
            elif la_hoa_don is False:
                quyet_dinh, ly_do = "CHAN", "Nova nói không phải hoá đơn"
            else:   # không có quyền gọi AWS, hết lượt, hoặc gọi lỗi: không đoán
                quyet_dinh, ly_do = "CHAN", "không chắc là hoá đơn, chụp lại rõ hơn"
            b["chi_tiet"] = f"Nova trả lời là hoá đơn: {la_hoa_don}"
    if quyet_dinh == "CHAN":
        kq["ly_do"] = ly_do
        return xong()

    # 2 và 3. PaddleOCR, trích, sensor
    with _buoc(cac_buoc, "paddle", "2. Đọc chữ: PaddleOCR") as b:
        rows, diem_ocr, so_khung = mo_hinh.doc_paddle(img)
        kq["diem_ocr"] = round(diem_ocr, 3)
        b["chi_tiet"] = f"{so_khung} khung chữ, điểm đọc trung bình {kq['diem_ocr']}"
    with _buoc(cac_buoc, "sensor", "3. Trích và sensor cộng tiền") as b:
        kq.update(logic.trich(rows))
        loi_paddle = logic.kiem_tra(rows, kq["tong_cong"]) if rows else ["không tìm thấy chữ"]
        b["chi_tiet"] = "; ".join(loi_paddle) or "các con số khớp nhau"

    # 4. Fallback AWS: Textract và Nova chạy song song, mỗi phiếu 2 lượt
    nova, loi_nova = None, None
    if logic.can_fallback(loi_paddle, kq["diem_ocr"]):
        with _buoc(cac_buoc, "fallback_aws", "4. Fallback: Textract và Nova Lite") as b:
            if not cho_phep_aws:
                b["chi_tiet"] = "cần đọc lại nhưng máy không có key AWS"
            elif not aws.han_muc.xin(2):
                b["chi_tiet"] = "cần đọc lại nhưng đã hết lượt AWS trong ngày"
            else:
                kq["da_goi_aws"] = True
                with ThreadPoolExecutor(2) as pool:
                    f_chu = pool.submit(_goi_aws, "textract", aws.doc_textract, img)
                    f_nova = pool.submit(_goi_aws, "nova_json", aws.doc_nova, img)
                    (chu, usd1), (nova, usd2) = f_chu.result(), f_nova.result()
                kq["chi_phi_usd"] += usd1 + usd2
                if chu is None or nova is None:
                    kq["loi_aws"] = True
                    b["chi_tiet"] = "gọi AWS lỗi hoặc Nova trả về sai mẫu, xem log"
                else:
                    loi_nova = logic.kiem_nova(nova, chu)
                    b["chi_tiet"] = "; ".join(loi_nova) or "Nova qua sensor độc lập"

    # 5. Cổng duyệt
    tong_nova = nova.get("tong_cong") if nova else None
    kq["trang_thai"], kq["nguon"], kq["ly_do"] = logic.cong_duyet(loi_paddle, loi_nova, kq["tong_cong"], tong_nova)
    if kq["nguon"] == "nova":
        kq.update(cua_hang=nova.get("cua_hang"), ngay=logic.tim_ngay([[nova.get("ngay") or ""]]),
                  tong_cong=tong_nova, danh_muc=logic.gan_danh_muc(nova.get("cua_hang")))
    return xong()
