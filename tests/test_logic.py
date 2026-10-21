"""Test logic lõi, không cần model hay key AWS, chạy dưới 1 giây.

    pytest                      chạy hết
    pytest -k todo1             chỉ test của TODO 1
"""
import logic

# Các hàng chữ y như PaddleOCR đọc ra từ easy_01.jpg (đã rơi dấu: "TNG CNG", "Tm tính")
ROWS = [["CÀ PH ĐƯNG PH"], ["Ngày: 08/01/2026"], ["Mì Qung gà", "3 x 48.000"], ["Trà đá", "3 × 5.000"],
        ["Tm tính:", "159.000"], ["-15.900d"], ["Giàm giá (10%):"], ["TNG CNG:", "143.100d"]]

NOVA_DUNG = {"la_hoa_don": True, "cua_hang": "CÀ PHÊ ĐƯỜNG PHỐ", "ngay": "08/01/2026",
             "mon": [{"ten": "Mì Quảng gà", "so_luong": 3, "don_gia": 48000}, {"ten": "Trà đá", "so_luong": 3, "don_gia": 5000}],
             "tam_tinh": 159000, "giam_gia": 15900, "tong_cong": 143100}
CHU_TEXTRACT = "CÀ PHÊ DU'O'NG PHO\nNgày: 08/01/2026\nTam tinh: 159.000\nGiam gia (10%): -15.900d\nTÔNG CÔNG: 143.100d"


# ---------- phần có sẵn ----------
def test_trich():
    assert logic.trich(ROWS) == {"cua_hang": "CÀ PH ĐƯNG PH", "ngay": "2026-01-08", "tong_cong": 143100, "danh_muc": "Đồ uống"}
    assert logic.tim_so([["TỔNG CỘNG:"], ["354.000đ"]], logic.DONG_TONG) == 354000   # con số nằm ở hàng dưới
    assert logic.gan_danh_muc("PH GIA TRUYN NAM ĐNH") == "Món chính"
    assert logic.gan_danh_muc("CỬA HÀNG ĐIỆN MÁY") == "Khác"
    assert logic.gan_danh_muc(None) == "Khác"


def test_kiem_ngay():
    assert logic.kiem_ngay("2026-01-08") == []
    assert logic.kiem_ngay(None) == ["không đọc được ngày"]
    assert len(logic.kiem_ngay("2028-06-27")) == 1   # OCR đọc 2026 thành 2028 (lỗi thật eval bắt được)
    assert len(logic.kiem_tra([r for r in ROWS if "Ngày" not in r[0]], 143100)) == 1


def test_cac_so():
    assert {159000, 15900, 143100} <= logic.cac_so(CHU_TEXTRACT)


# ---------- TODO 1 ----------
def test_todo1_cong_vao():
    assert logic.quyet_cong_vao(net=300, diem=0.95) == ("QUA", "")
    assert logic.quyet_cong_vao(net=1, diem=0.95)[0] == "CHAN"            # mờ thì chặn, dù SigLIP chấm cao
    assert logic.quyet_cong_vao(net=1, diem=0.05) == ("CHAN", "ảnh bị mờ")   # kiểm mờ trước
    assert logic.quyet_cong_vao(net=300, diem=0.05) == ("CHAN", "không giống hoá đơn")
    assert logic.quyet_cong_vao(net=300, diem=0.5)[0] == "HOI_VLM"         # SigLIP không chắc thì hỏi Nova


# ---------- TODO 2 ----------
def test_todo2_sensor():
    assert logic.kiem_tra(ROWS, 143100) == []
    assert logic.kiem_tra(ROWS, None) == ["không thấy dòng TỔNG CỘNG"]       # dòng tổng bị che
    assert len(logic.kiem_tra(ROWS, 50000)) == 1                             # tổng bị đọc sai hoặc bị sửa
    assert len(logic.kiem_tra(ROWS[:2] + ROWS[3:], 143100)) == 1             # OCR bỏ sót một món


# ---------- TODO 3 ----------
def test_todo3_can_fallback():
    assert logic.can_fallback([], 0.97) is False
    assert logic.can_fallback(["không thấy dòng TỔNG CỘNG"], 0.97) is True
    assert logic.can_fallback([], 0.6) is True                               # sensor qua nhưng đọc không tự tin


# ---------- TODO 4 ----------
def test_todo4_kiem_nova():
    assert logic.kiem_nova(NOVA_DUNG, CHU_TEXTRACT) == []
    # Dòng tổng bị che: Nova tự tính 143.100 và các con số vẫn khớp nhau, nhưng con số đó không có trên ảnh
    che = CHU_TEXTRACT.replace("\nTÔNG CÔNG: 143.100d", "")
    assert len(logic.kiem_nova(NOVA_DUNG, che)) == 1
    assert logic.kiem_nova({**NOVA_DUNG, "tong_cong": None}, CHU_TEXTRACT) == ["Nova không thấy dòng TỔNG CỘNG"]
    assert logic.kiem_nova({"la_hoa_don": False}, "") == ["Nova nói đây không phải hoá đơn"]
    assert logic.kiem_nova(None, "") == ["Nova nói đây không phải hoá đơn"]
    # Ảnh chất lượng thấp: tổng đúng nhưng Nova bịa ngày (lỗi thật eval bắt được)
    assert len(logic.kiem_nova({**NOVA_DUNG, "ngay": "20/03/2026"}, CHU_TEXTRACT)) == 1
    # Hoá đơn không giảm giá bị che dòng tổng: Nova ghi tổng = tạm tính, con số có trên ảnh nhưng ở dòng Tạm tính
    khong_giam = {**NOVA_DUNG, "giam_gia": 0, "tong_cong": 159000}
    assert len(logic.kiem_nova(khong_giam, che)) == 1


# ---------- TODO 5 ----------
def test_todo5_cong_duyet():
    assert logic.cong_duyet([], None) == (logic.GHI_SO, "paddle", "các con số khớp nhau")
    assert logic.cong_duyet(["không thấy dòng TỔNG CỘNG"], [])[:2] == (logic.GHI_SO, "nova")
    assert logic.cong_duyet([], ["tổng không có trên ảnh"])[:2] == (logic.GHI_SO, "paddle")   # Paddle qua là đủ
    trang_thai, nguon, ly_do = logic.cong_duyet(["không thấy dòng TỔNG CỘNG"], ["tổng không có trên ảnh"])
    assert (trang_thai, nguon) == (logic.CAN_NGUOI_XEM, "")
    assert "TỔNG CỘNG" in ly_do and "không có trên ảnh" in ly_do
    assert logic.cong_duyet(["không thấy dòng TỔNG CỘNG"], None)[0] == logic.CAN_NGUOI_XEM   # không gọi được AWS
    # Cả hai nguồn qua sensor nhưng đọc tổng khác nhau: không chọn bừa một bên
    assert logic.cong_duyet([], [], 143100, 150000)[0] == logic.CAN_NGUOI_XEM
    assert logic.cong_duyet([], [], 143100, 143100)[:2] == (logic.GHI_SO, "nova")
