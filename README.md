# Buổi 23 · Capstone: ảnh hoá đơn vào, sổ chi tiêu ra

Một web app hoàn chỉnh ráp mọi thứ đã học từ Buổi 20 đến 23. Model chỉ là linh kiện. Thứ làm app đáng tin là **harness** quanh model: cổng chặn sớm, sensor độc lập, fallback có kiểm soát, cổng duyệt, log, metric và eval.

```
ảnh ─▶ 1. Cổng vào ──────────▶ 2. PaddleOCR ─▶ 3. Trích + sensor ─┬─ khớp, đọc tự tin ─────────────▶ GHI SỔ (paddle)
        độ nét, SigLIP 2 (ViT)    tìm khung,       tổng, ngày,      │
        không chắc: hỏi Nova      đọc chữ          danh mục         └─ lỗi hoặc điểm thấp ─▶ 4. Fallback AWS
        (VQA tầng 2)                                                    Textract ∥ Nova Lite JSON
                                                                        sensor độc lập: tổng của Nova
                                                                        phải có trong chữ Textract ─▶ 5. Cổng duyệt
                                                                                                        GHI SỔ (nova) / CẦN NGƯỜI XEM
```

| Bước | Buổi | Làm bằng gì | Tốn |
|---|---|---|---|
| 1. Cổng vào | 22, 23 | Độ nét (variance of Laplacian), SigLIP 2 zero-shot. Điểm lưng chừng thì hỏi Nova Lite | 0,2 giây, miễn phí |
| 2. Đọc chữ | 20, 21 | PaddleOCR `PP-OCRv5_mobile_det`, `latin_PP-OCRv5_mobile_rec` | 2–6 giây CPU, miễn phí |
| 3. Trích, sensor | 22, 23 | Regex chịu lỗi OCR; các món cộng lại = tạm tính, tạm tính − giảm giá = tổng | dưới 1 ms |
| 4. Fallback | 21, 22 | Textract và Nova Lite chạy song song, chỉ khi sensor lỗi hoặc điểm đọc < 0,85. Tổng và ngày của Nova phải khớp chữ Textract đọc trên dòng TỔNG CỘNG | khoảng 5 giây, $0,0017 mỗi phiếu |
| 5. Cổng duyệt | 22 | Có một nguồn qua sensor thì ghi sổ; hai nguồn đọc tổng khác nhau hoặc không nguồn nào qua thì chuyển người | dưới 1 ms |

## Cấu trúc

| File | Việc |
|---|---|
| `logic.py` | **Logic lõi, 5 TODO.** Code thường, không gọi model, test trong 1 giây |
| `mo_hinh.py` | SigLIP 2 và PaddleOCR chạy trên máy |
| `aws.py` | Textract, Nova Lite; hạn mức lượt mỗi ngày, timeout, kiểm kiểu JSON của Nova |
| `pipeline.py` | Ráp 5 bước theo thứ tự, đo giờ từng bước |
| `giam_sat.py` | Log JSON, metric Prometheus, thống kê p50/p95 |
| `server.py` | FastAPI: trang web, `/api/hoa-don`, `/api/thong-ke`, `/metrics`, `/docs` |
| `static/index.html` | Trang web kéo thả ảnh, bảng từng bước, bảng monitoring |
| `danhgia.py` | Eval trên 30 hoá đơn × 3 dạng ảnh, chạy song song bằng Ray |
| `tests/` | Test logic, test cả chuỗi và API bằng model giả và AWS giả |
| `ban_hoc_vien.py` | Chỉ có ở nhánh `main`: sinh bản học viên cho nhánh `dev` (xoá lời giải 5 TODO) |

## Hai nhánh

| Nhánh | Nội dung | Dùng khi |
|---|---|---|
| `dev` | 5 TODO trong `logic.py` còn trống (`raise NotImplementedError`) | Học viên clone về làm trên lớp |
| `main` | Lời giải đầy đủ | Đối chiếu sau khi làm xong |

```bash
git clone -b dev https://github.com/lequocduyquang/receipt-capstone.git
```

Nhánh `dev` luôn được sinh từ `main` bằng `ban_hoc_vien.py`, không sửa tay:

```bash
git worktree add ../receipt-capstone-dev dev      # một lần
python ban_hoc_vien.py ../receipt-capstone-dev    # rồi commit trong worktree đó
```

## 5 TODO trong `logic.py`

| TODO | Hàm | Bài học |
|---|---|---|
| 1 | `quyet_cong_vao` | Rẻ và chắc trước: kiểm mờ trước SigLIP; SigLIP không chắc thì hỏi VLM, không đoán |
| 2 | `kiem_tra` | Sensor kiểm trên chữ thật trên ảnh, không tin con số model tự khai |
| 3 | `can_fallback` | Gọi dịch vụ tốn tiền chỉ khi có bằng chứng tầng rẻ đáng ngờ |
| 4 | `kiem_nova` | Nova vừa đọc vừa tự tính, nên cộng tiền khớp chưa đủ: tổng phải nằm trên dòng TỔNG CỘNG mà Textract đọc được |
| 5 | `cong_duyet` | Chỉ ghi sổ khi có bằng chứng. Hai nguồn cãi nhau hoặc không chắc thì chuyển người |

Mỗi TODO có test riêng: `pytest -k todo1` đến `pytest -k todo5`. Xong cả 5 thì `pytest` báo 21 passed (bản lời giải có thêm 1 test cho `ban_hoc_vien.py`, ra 22 passed).

## Chạy trên máy

Cần Python 3.12 (PaddlePaddle 3.2 chưa có bản cho 3.13 trở lên).

```bash
python3.12 -m venv capenv && source capenv/bin/activate     # Windows: capenv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                   # không tải model, không cần key, dưới 3 giây
uvicorn server:app --port 7860           # mở http://127.0.0.1:7860, lần đầu tải 1,5 GB model
python danhgia.py --n 10 --dang che      # eval 10 hoá đơn bị che dòng tổng, miễn phí
```

Máy chỉ có Python 3.13 trở lên: `pip install uv`, rồi `uv venv --python 3.12 capenv` và `uv pip install -r requirements-dev.txt`.

### Bật fallback AWS (tuỳ chọn)

Không có key AWS thì app vẫn chạy đủ, chỉ là ca khó chuyển người. Có key `ml-user` (lấy ở trang key của lớp) thì:

```bash
cp .env.example .env        # rồi điền AWS_ACCESS_KEY_ID và AWS_SECRET_ACCESS_KEY
uvicorn server:app --port 7860           # app tự đọc .env khi khởi động
python danhgia.py --aws --ray 4          # eval 90 ảnh có fallback, khoảng $0,06
```

Không bao giờ commit hay gửi file `.env` lên group. Ba lớp bảo vệ tiền AWS:
1. Key `ml-user` chỉ có quyền Textract và Nova Lite, hết hạn 31/12/2026.
2. Mỗi ngày tối đa `AWS_MOI_NGAY` lượt (mặc định 300). Đếm trong bộ nhớ nên khởi động lại server là đếm lại.
3. Timeout 20 giây và tối đa 3 lần thử mỗi lượt gọi, không treo vô hạn.

Upload chỉ nhận JPEG, PNG, WEBP, tối đa 10 MB và 40 triệu điểm ảnh.

Mạng công ty có proxy chèn chứng chỉ (lỗi `CERTIFICATE_VERIFY_FAILED`) thì tải model và gọi AWS đều lỗi; chạy ở mạng khác. Nếu máy đặt `AWS_CA_BUNDLE` trỏ vào chứng chỉ của proxy mà proxy đang tắt, chạy với `env -u AWS_CA_BUNDLE`.

## Monitoring

| Câu hỏi vận hành | Xem ở đâu |
|---|---|
| App có chạy đúng không? | Bảng Monitoring trên trang web, `receipts_total{trang_thai,nguon}` |
| Chậm ở bước nào? | Bảng từng bước của mỗi ảnh, `step_seconds{buoc}` (histogram), p50/p95 |
| Tốn bao nhiêu tiền? | `aws_calls_total{dich_vu,ket_qua}`, `aws_cost_usd_total`, lượt AWS còn lại hôm nay |
| Một ảnh cụ thể ra sao? | Terminal đang chạy `uvicorn`: mỗi ảnh một dòng JSON `"su_kien": "ket_qua"` |

`/metrics` theo chuẩn Prometheus, gắn vào Grafana hay bất kỳ hệ thống nào đọc được Prometheus.

## Eval

Đo ngày 21/10/2026 trên MacBook M5, `python danhgia.py --ray 4` và `python danhgia.py --ray 4 --aws`. "Ghi sổ đúng" là tổng tiền, ngày và danh mục đều đúng.

| Dạng ảnh (30 hoá đơn) | Fallback AWS | Ghi sổ đúng | Sai mà lọt | Chuyển người | Bị chặn | Gọi AWS | p50 / p95 giây | $ |
|---|---|---|---|---|---|---|---|---|
| Gốc | tắt | 30 | 0 | 0 | 0 | 0 | 5,0 / 6,6 | 0 |
| Gốc | bật | 30 | 0 | 0 | 0 | 0 | 5,2 / 8,6 | 0 |
| Che dòng TỔNG CỘNG | tắt | 0 | 0 | 30 | 0 | 0 | 4,6 / 6,3 | 0 |
| Che dòng TỔNG CỘNG | bật | 0 | 0 | 30 | 0 | 30 | 7,1 / 10,4 | 0,050 |
| Chất lượng thấp (60%, JPEG 30) | tắt | 22 | 0 | 7 | 1 | 0 | 4,2 / 5,5 | 0 |
| Chất lượng thấp (60%, JPEG 30) | bật | **26** | 0 | 4 | 0 | 8 | 4,3 / 7,7 | 0,012 |

Đọc bảng:
- **Sai mà lọt bằng 0 ở cả 180 lượt.** Buổi 22, Nova + harness lọt 8/10 hoá đơn che dòng tổng; ở đây Nova vẫn bịa tổng, nhưng sensor độc lập (tổng phải nằm trên dòng TỔNG CỘNG mà Textract đọc được) bắt hết.
- Fallback chỉ gọi AWS cho ca đáng ngờ: 8 trên 30 ảnh xấu, cứu thêm 4 phiếu và 1 ảnh SigLIP chấm lưng chừng. Ảnh rõ không tốn đồng nào.
- Eval từng bắt được 2 lỗi thật và code đã sửa theo: Nova bịa ngày trên ảnh xấu, PaddleOCR đọc 2026 thành 2028. Cả hai giờ bị chặn bởi `kiem_ngay` và phép so ngày với Textract.
- Ảnh xấu hơn (35%, JPEG 25) thì chính Nova cũng cộng sai, mọi phiếu chuyển người. Đó là đúng thiết kế.

Luật trích và sensor chỉnh trên đúng 30 hoá đơn này (6 quán), nên số trên là lạc quan. Thêm hoá đơn thật chưa từng nhìn vào `data/receipts/labels.json` để có số thật.
