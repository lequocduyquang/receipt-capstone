"""Logic lõi của harness: code thường, không gọi model, test được trong vài mili giây.

Học viên làm 5 TODO trong file này, chạy `pytest` để kiểm:
  TODO 1  quyet_cong_vao   cổng vào: chặn, cho qua, hay hỏi thêm VLM (cascade của Buổi 22)
  TODO 2  kiem_tra         sensor cộng tiền trên chữ PaddleOCR đọc được
  TODO 3  can_fallback     khi nào phải gọi Bedrock đọc lại
  TODO 4  kiem_nova        sensor độc lập cho Nova: tổng phải nằm trên dòng TỔNG CỘNG mà Textract đọc được
  TODO 5  cong_duyet       chọn kết quả cuối cùng: ghi sổ hay chuyển người
"""
import difflib
import re
import unicodedata
from datetime import date

# Ngưỡng. Mỗi con số đều đo trên 30 hoá đơn của Buổi 20, 21 (xem README, phần Eval).
NGUONG_MO = 50              # độ nét (variance of Laplacian) trên ảnh cạnh dài 1.280 px: hoá đơn rõ > 200, ảnh mờ < 2
DIEM_CHAC_LA_HOA_DON = 0.7  # SigLIP 2 chấm từ đây trở lên: cho qua
DIEM_CHAC_KHONG_PHAI = 0.3  # dưới mức này: chặn. Ở giữa: hỏi Nova (VQA tầng 2)
NGUONG_DIEM_OCR = 0.85      # điểm đọc chữ trung bình của PaddleOCR: hoá đơn rõ khoảng 0,95; ảnh xấu 0,5 đến 0,8

GHI_SO = "GHI SỔ"
CAN_NGUOI_XEM = "CẦN NGƯỜI XEM"
CHAN = "CHẶN"


# ================================================================
# Đọc chữ OCR: chịu lỗi rơi dấu
# ================================================================
def bo_dau(s):
    """'TỔNG CỘNG' thành 'TONG CONG': model đọc chữ hay sai dấu, so khớp không dấu cho chắc."""
    s = unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def thanh_so(chu):
    """'395.100đ' thành 395100."""
    return int(re.sub(r"\D", "", chu))


def cac_so(chu):
    """Mọi con số tiền trong một đoạn chữ: '3 x 48.000 ... 143.100đ' thành {3, 48000, 143100}."""
    return {thanh_so(s) for s in re.findall(r"\d[\d.,]*\d|\d", chu)}


# Model đọc chữ hay làm rơi chữ có dấu chồng: "TỔNG CỘNG" thường ra "TNG CNG", nên cho phép thiếu một chữ.
DONG_TONG = r"T\w?NG C\w?NG"
DONG_TAM_TINH = r"T\w?M T\w*NH"


def tim_so(rows, mau):
    """Tìm hàng khớp mẫu (ví dụ DONG_TONG), lấy con số cuối trong hàng đó hoặc hàng ngay dưới."""
    for i, row in enumerate(rows):
        if re.search(mau, bo_dau(" ".join(row))):
            for hang in rows[i:i + 2]:
                so = re.findall(r"\d[\d.,]*\d", " ".join(hang))
                if so:
                    return thanh_so(so[-1])
    return None


def tim_ngay(rows):
    """Ngày dạng DD/MM/YYYY trong hoá đơn, trả về YYYY-MM-DD."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", " ".join(" ".join(r) for r in rows))
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else None


DANH_MUC = {"Đồ uống": ["CA PHE", "TRA SUA"], "Bánh": ["BANH"], "Món chính": ["PHO GIA", "BUN BO", "COM TAM"]}


def giong(tu_khoa, ten):
    """Độ giống (0 đến 1) của từ khoá với đoạn giống nhất trong tên. "CA PH" vẫn giống "CA PHE"."""
    n = len(tu_khoa)
    return max(difflib.SequenceMatcher(None, tu_khoa, ten[i:i + n + 1]).ratio() for i in range(max(1, len(ten) - n + 1)))


def gan_danh_muc(ten_cua_hang):
    """Gắn danh mục theo từ khoá gần đúng trong tên cửa hàng."""
    # ponytail: từ khoá chỉnh theo 6 quán của bộ 30 hoá đơn; nhiều loại chứng từ hơn thì thay bằng text classifier
    ten = bo_dau(ten_cua_hang or "")
    if not ten:
        return "Khác"
    diem, danh_muc = max((giong(k, ten), dm) for dm, ks in DANH_MUC.items() for k in ks)
    return danh_muc if diem >= 0.7 else "Khác"


def tong_cac_mon(rows):
    """Cộng số lượng × đơn giá của mọi hàng dạng "3 x 48.000"."""
    chu = " ".join(" ".join(r) for r in rows)
    return sum(int(sl) * thanh_so(gia) for sl, gia in re.findall(r"(\d+) ?[x×] ?(\d[\d.,]*\d)", chu))


def tien_giam(rows):
    """Số tiền có dấu trừ, ví dụ "-43.900". Hoá đơn nghiêng hay tách con số khỏi chữ "Giảm giá", nên tìm theo dấu trừ."""
    # ponytail: số điện thoại "090-123-4567" cũng bị tính là giảm giá. Sai theo hướng an toàn (sensor lệch, đi fallback)
    return sum(thanh_so(s) for s in re.findall(r"-(\d[\d.,]*\d)", " ".join(" ".join(r) for r in rows)))


def kiem_ngay(ngay):
    """Policy hoàn ứng: phải đọc được ngày, và chỉ nhận hoá đơn của năm nay.
    Sensor cộng tiền không bắt được ngày đọc sai, nên ngày cần phép kiểm riêng (eval 21/10/2026: OCR đọc 2026 thành 2028)."""
    # ponytail: "năm nay" là policy đơn giản nhất; công ty thật dùng kỳ quyết toán và hạn nộp chứng từ
    if ngay is None:
        return ["không đọc được ngày"]
    if not ngay.startswith(str(date.today().year)):
        return [f"ngày {ngay} không thuộc năm nay"]
    return []


def trich(rows):
    """Tên quán, ngày, tổng tiền, danh mục từ các hàng chữ OCR."""
    cua_hang = " ".join(rows[0]) if rows else ""
    return {"cua_hang": cua_hang, "ngay": tim_ngay(rows), "tong_cong": tim_so(rows, DONG_TONG),
            "danh_muc": gan_danh_muc(cua_hang)}


# ================================================================
# TODO 1 · Cổng vào
# ================================================================
def quyet_cong_vao(net, diem):
    """net: độ nét của ảnh. diem: SigLIP 2 chấm "đây là ảnh hoá đơn", từ 0 đến 1.
    Trả về (quyet_dinh, ly_do), quyet_dinh là "CHAN", "QUA" hoặc "HOI_VLM"."""
    # TODO 1: kiểm theo đúng thứ tự, rẻ và chắc trước:
    #   - net < NGUONG_MO                     thì ("CHAN", "ảnh bị mờ")       ảnh mờ cũng không còn giống hoá đơn, nên kiểm mờ trước
    #   - diem >= DIEM_CHAC_LA_HOA_DON        thì ("QUA", "")
    #   - diem < DIEM_CHAC_KHONG_PHAI         thì ("CHAN", "không giống hoá đơn")
    #   - còn lại, SigLIP không chắc          thì ("HOI_VLM", "SigLIP không chắc")
    raise NotImplementedError("TODO 1")


# ================================================================
# TODO 2 · Sensor cộng tiền trên chữ PaddleOCR
# ================================================================
def kiem_tra(rows, tong_cong):
    """Trả về danh sách lỗi, rỗng nghĩa là các con số trên hoá đơn khớp nhau.
    Kiểm trên chữ OCR thật trên ảnh, nên không model nào "tự tính cho khớp" được."""
    loi = kiem_ngay(tim_ngay(rows))
    tam_tinh = tim_so(rows, DONG_TAM_TINH)
    if tong_cong is None:
        loi.append("không thấy dòng TỔNG CỘNG")
    if tam_tinh is None:
        loi.append("không thấy dòng Tạm tính")
        return loi
    # TODO 2: thêm 2 phép kiểm, sai thì loi.append(một câu mô tả), kiểm phép thứ hai chỉ khi phép đầu qua:
    #   - tong_cac_mon(rows) phải bằng tam_tinh                (OCR bỏ sót hoặc đọc sai một món)
    #   - tam_tinh - tien_giam(rows) phải bằng tong_cong       (OCR đọc sai tổng, hoặc ai đó sửa tổng)
    #   tong_cong có thể là None (đã báo lỗi ở trên), khi đó bỏ qua phép thứ hai.
    raise NotImplementedError("TODO 2")
    return loi


# ================================================================
# TODO 3 · Khi nào gọi Bedrock đọc lại
# ================================================================
def can_fallback(loi, diem_ocr):
    """loi: lỗi sensor của PaddleOCR. diem_ocr: điểm đọc chữ trung bình, từ 0 đến 1."""
    # TODO 3: gọi Bedrock khi sensor báo lỗi, HOẶC khi PaddleOCR đọc không tự tin (diem_ocr < NGUONG_DIEM_OCR).
    raise NotImplementedError("TODO 3")


# ================================================================
# TODO 4 · Sensor độc lập cho Nova
# ================================================================
def kiem_nova(nova, chu_textract):
    """nova: JSON Nova đọc từ ảnh (aws.py đã kiểm đúng kiểu dữ liệu). chu_textract: chữ Textract đọc được, mỗi dòng một hàng.
    Nova vừa đọc vừa tự tính, nên cộng tiền khớp chưa đủ (Buổi 22: che dòng tổng, Nova bịa tổng và lọt 8/10).
    Bằng chứng độc lập: con số tổng Nova khai phải nằm đúng trên dòng TỔNG CỘNG mà Textract đọc được."""
    if not nova or not nova.get("la_hoa_don"):
        return ["Nova nói đây không phải hoá đơn"]
    tong, tam_tinh, giam = nova.get("tong_cong"), nova.get("tam_tinh") or 0, nova.get("giam_gia") or 0
    if tong is None:
        return ["Nova không thấy dòng TỔNG CỘNG"]
    loi = []
    cac_mon = sum(m["so_luong"] * m["don_gia"] for m in nova.get("mon") or [])
    if cac_mon != tam_tinh:
        loi.append(f"Nova: các món cộng lại {cac_mon} khác tạm tính {tam_tinh}")
    if tam_tinh - giam != tong:
        loi.append(f"Nova: tạm tính {tam_tinh} trừ giảm giá {giam} khác tổng cộng {tong}")
    # Eval ngày 21/10/2026 bắt được 2 phiếu ảnh chất lượng thấp "sai mà lọt": tổng đúng nhưng Nova bịa ngày.
    ngay = tim_ngay([[nova.get("ngay") or ""]])
    if ngay != tim_ngay([[chu_textract]]):
        loi.append(f"ngày {nova.get('ngay')} của Nova khác ngày Textract đọc thấy")
    loi += kiem_ngay(ngay)
    # TODO 4: phép kiểm độc lập cho tổng tiền: tổng Textract đọc trên dòng TỔNG CỘNG phải bằng tong của Nova.
    #   Gợi ý: dùng lại tim_so và DONG_TONG như với PaddleOCR. tim_so nhận danh sách hàng, mỗi hàng là list chữ;
    #   chu_textract là một chuỗi, mỗi dòng (splitlines) là một hàng.
    #   Không bằng thì loi.append(f"tổng {tong} của Nova không có trên dòng TỔNG CỘNG mà Textract đọc được")
    #   Vì sao không chỉ hỏi "con số có ở đâu đó trên ảnh"? Che dòng tổng của hoá đơn không giảm giá thì
    #   Nova ghi tổng = tạm tính, và con số đó vẫn có trên ảnh, ở dòng Tạm tính.
    raise NotImplementedError("TODO 4")
    return loi


# ================================================================
# TODO 5 · Cổng duyệt
# ================================================================
def cong_duyet(loi_paddle, loi_nova, tong_paddle=None, tong_nova=None):
    """loi_paddle: lỗi sensor của PaddleOCR. loi_nova: lỗi của kiem_nova, hoặc None nếu không gọi được AWS.
    tong_paddle, tong_nova: tổng tiền mỗi nguồn đọc ra.
    Trả về (trang_thai, nguon, ly_do), nguon là "paddle", "nova" hoặc "" khi chuyển người."""
    # TODO 5: chỉ ghi sổ khi có bằng chứng. Xét theo thứ tự:
    #   - cả hai nguồn qua sensor mà tong_paddle != tong_nova   thì (CAN_NGUOI_XEM, "", "Paddle và Nova đọc tổng khác nhau")
    #   - loi_nova là [] (đã gọi AWS và qua sensor)            thì (GHI_SO, "nova", "Nova đọc lại, tổng khớp dòng TỔNG CỘNG")
    #   - loi_paddle rỗng                                      thì (GHI_SO, "paddle", "các con số khớp nhau")
    #   - còn lại                                              thì (CAN_NGUOI_XEM, "", "; ".join(loi_paddle + (loi_nova or [])))
    #   Phân biệt loi_nova == [] (gọi rồi, không lỗi) với loi_nova is None (không gọi).
    raise NotImplementedError("TODO 5")
