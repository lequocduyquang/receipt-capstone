"""Test cả chuỗi và API bằng model giả và AWS giả: kiểm cách ráp các bước, không tải model, không tốn tiền."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import aws
import logic
import mo_hinh
import pipeline
from test_logic import CHU_TEXTRACT, NOVA_DUNG, ROWS

ANH = Image.new("RGB", (400, 600), "white")


@pytest.fixture
def gia(monkeypatch):
    """Model giả: ảnh rõ, chắc là hoá đơn, Paddle đọc đúng easy_01. Mỗi test sửa lại phần mình cần."""
    goi = []
    monkeypatch.setattr(mo_hinh, "do_net", lambda img: 300)
    monkeypatch.setattr(mo_hinh, "diem_hoa_don", lambda img: 0.95)
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: (ROWS, 0.97, 8))
    monkeypatch.setattr(aws, "hoi_nova", lambda img, q: goi.append("vqa") or (True, 0.0001))
    monkeypatch.setattr(aws, "doc_textract", lambda img: goi.append("textract") or (CHU_TEXTRACT, 0.0015))
    monkeypatch.setattr(aws, "doc_nova", lambda img: goi.append("nova") or (NOVA_DUNG, 0.0002))
    monkeypatch.setattr(aws, "han_muc", aws.HanMuc(100))
    return goi


def test_hoa_don_ro_khong_goi_aws(gia):
    kq = pipeline.xu_ly(ANH, cho_phep_aws=True)
    assert (kq["trang_thai"], kq["nguon"], kq["tong_cong"]) == (logic.GHI_SO, "paddle", 143100)
    assert gia == [] and kq["chi_phi_usd"] == 0


def test_anh_mo_bi_chan_truoc_ocr(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "do_net", lambda img: 1)
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: pytest.fail("ảnh mờ không được tốn công OCR"))
    assert pipeline.xu_ly(ANH)["trang_thai"] == logic.CHAN


def test_siglip_khong_chac_thi_hoi_nova(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "diem_hoa_don", lambda img: 0.5)
    assert pipeline.xu_ly(ANH, cho_phep_aws=True)["trang_thai"] == logic.GHI_SO
    assert gia == ["vqa"]
    assert pipeline.xu_ly(ANH, cho_phep_aws=False)["trang_thai"] == logic.CHAN   # không có key AWS: không đoán


def test_che_dong_tong_nova_bia_so_van_bi_bat(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: (ROWS[:-1], 0.97, 7))
    monkeypatch.setattr(aws, "doc_textract", lambda img: (CHU_TEXTRACT.replace("\nTÔNG CÔNG: 143.100d", ""), 0.0015))
    kq = pipeline.xu_ly(ANH, cho_phep_aws=True)
    assert kq["trang_thai"] == logic.CAN_NGUOI_XEM and kq["da_goi_aws"]


def test_doc_khong_tu_tin_thi_nova_doc_lai(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: (ROWS[:-1], 0.6, 7))
    kq = pipeline.xu_ly(ANH, cho_phep_aws=True)
    assert (kq["trang_thai"], kq["nguon"], kq["ngay"], kq["danh_muc"]) == (logic.GHI_SO, "nova", "2026-01-08", "Đồ uống")
    assert sorted(gia) == ["nova", "textract"] and kq["chi_phi_usd"] > 0


def test_het_han_muc_thi_chuyen_nguoi(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: (ROWS[:-1], 0.97, 7))
    monkeypatch.setattr(aws, "han_muc", aws.HanMuc(1))   # cần 2 lượt, chỉ còn 1
    assert pipeline.xu_ly(ANH, cho_phep_aws=True)["trang_thai"] == logic.CAN_NGUOI_XEM
    assert gia == []


def test_doc_khong_tu_tin_aws_loi_van_giu_paddle(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: (ROWS, 0.6, 8))   # sensor qua, điểm đọc thấp
    monkeypatch.setattr(aws, "doc_nova", lambda img: (None, 0.0002))           # Nova trả về sai mẫu
    kq = pipeline.xu_ly(ANH, cho_phep_aws=True)
    assert (kq["trang_thai"], kq["nguon"]) == (logic.GHI_SO, "paddle")


def test_aws_loi_thi_chuyen_nguoi_khong_sap(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: (ROWS[:-1], 0.97, 7))
    def nova_treo(img):
        raise TimeoutError("read timeout")
    monkeypatch.setattr(aws, "doc_nova", nova_treo)
    kq = pipeline.xu_ly(ANH, cho_phep_aws=True)
    assert kq["trang_thai"] == logic.CAN_NGUOI_XEM and kq["loi_aws"]


# ---------- API ----------
@pytest.fixture
def client(gia, monkeypatch):
    monkeypatch.setattr(mo_hinh, "tai_model", lambda: None)
    import server
    with TestClient(server.app) as c:
        yield c


def _jpeg():
    b = io.BytesIO()
    ANH.save(b, "JPEG")
    return b.getvalue()


def test_api_nhan_anh(client):
    r = client.post("/api/hoa-don", files={"anh": ("a.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["trang_thai"] == logic.GHI_SO
    assert client.get("/api/thong-ke").json()["so_hoa_don"] >= 1
    assert b"receipts_total" in client.get("/metrics").content


def test_api_tu_choi_file_khong_phai_anh(client):
    assert client.post("/api/hoa-don", files={"anh": ("a.txt", b"hello", "text/plain")}).status_code == 415


def test_api_tu_choi_dinh_dang_la(client):
    b = io.BytesIO()
    ANH.save(b, "TIFF")
    assert client.post("/api/hoa-don", files={"anh": ("a.tif", b.getvalue(), "image/tiff")}).status_code == 415


def test_api_loi_bat_ngo_van_len_metric(client, monkeypatch):
    monkeypatch.setattr(mo_hinh, "doc_paddle", lambda img: 1 / 0)
    assert client.post("/api/hoa-don", files={"anh": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 500
    assert 'trang_thai="LỖI"' in client.get("/metrics").text


def test_nova_sai_kieu_bi_loai():
    from test_logic import NOVA_DUNG
    assert aws.hop_le(NOVA_DUNG)
    assert not aws.hop_le({**NOVA_DUNG, "tam_tinh": "159.000"})
    assert not aws.hop_le({**NOVA_DUNG, "mon": [{"so_luong": "3", "don_gia": 48000}]})
    assert not aws.hop_le({**NOVA_DUNG, "ngay": 20260108})

