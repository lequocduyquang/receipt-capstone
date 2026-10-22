"""Model chạy trên máy (miễn phí): SigLIP 2 cho cổng vào, PaddleOCR tìm khung và đọc chữ."""
import threading
from functools import cache

import cv2
import numpy as np
import torch
from PIL import ImageOps

CANH_DAI = 1280   # ảnh điện thoại 4000 px được thu về cỡ này, không thì độ nét tụt và ảnh rõ cũng bị chặn
CAU_HOA_DON = "Đây là ảnh chụp một tờ hoá đơn."   # câu tách hoá đơn với ảnh khác tốt nhất (đo ở Buổi 22)

# ponytail: một khoá chung cho mọi model, mỗi lúc chỉ một ảnh được suy luận.
# Đủ cho một máy; cần nhiều người dùng cùng lúc thì chạy nhiều bản (nhiều worker) thay vì bỏ khoá.
_khoa = threading.Lock()


@cache
def tai_model():
    """Tải 3 model ở lần gọi đầu, khoảng 1,5 GB, các lần sau dùng lại."""
    from paddleocr import TextDetection, TextRecognition
    from transformers import AutoModel, AutoProcessor
    siglip = AutoModel.from_pretrained("google/siglip2-base-patch16-224").eval()   # Buổi 22, 23
    processor = AutoProcessor.from_pretrained("google/siglip2-base-patch16-224")
    det = TextDetection(model_name="PP-OCRv5_mobile_det")          # Buổi 20
    rec = TextRecognition(model_name="latin_PP-OCRv5_mobile_rec")   # Buổi 21
    return siglip, processor, det, rec


def chuan_hoa(img):
    """Xoay ảnh điện thoại cho đúng chiều (EXIF) và thu về cạnh dài ≤ CANH_DAI."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((CANH_DAI, CANH_DAI))
    return img


def do_net(img):
    """Ảnh mờ thì ít cạnh sắc, nên phương sai của Laplacian nhỏ. Cách cổ điển, không cần model."""
    return float(cv2.Laplacian(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())


@torch.no_grad()
def diem_hoa_don(img):
    """SigLIP 2 chấm ảnh khớp câu "Đây là ảnh chụp một tờ hoá đơn." bằng sigmoid(t × cos + b), như Buổi 22."""
    siglip, processor, _, _ = tai_model()
    x = processor(text=[CAU_HOA_DON], images=[img], padding="max_length", max_length=64, return_tensors="pt")
    with _khoa:
        return torch.sigmoid(siglip(**x).logits_per_image)[0, 0].item()


def crop_line(img, poly):
    """Cắt một khung 4 góc (có thể nghiêng) thành ảnh chữ nhật nằm thẳng."""
    p = np.float32(poly)
    w = int(max(np.linalg.norm(p[0] - p[1]), np.linalg.norm(p[3] - p[2])))
    h = int(max(np.linalg.norm(p[0] - p[3]), np.linalg.norm(p[1] - p[2])))
    M = cv2.getPerspectiveTransform(p, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    return cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def group_rows(texts, polys):
    """Xếp các khung thành hàng theo thứ tự đọc (trên xuống, trái sang phải), chịu được ảnh nghiêng."""
    P = np.array(polys, float)
    angle = np.median(np.arctan2(P[:, 1, 1] - P[:, 0, 1], P[:, 1, 0] - P[:, 0, 0]))
    center = P.mean(axis=1)
    u = center @ [np.cos(angle), np.sin(angle)]
    v = center @ [-np.sin(angle), np.cos(angle)]
    h = np.linalg.norm(P[:, 3] - P[:, 0], axis=1)
    rows = []
    for i in np.argsort(v):
        if rows and abs(v[i] - v[rows[-1][-1]]) < h[i] / 2:
            rows[-1].append(i)
        else:
            rows.append([i])
    return [[texts[i] for i in sorted(r, key=lambda i: u[i])] for r in rows]


def doc_paddle(img):
    """PaddleOCR tìm khung rồi đọc chữ. Trả về (các hàng chữ, điểm đọc trung bình, số khung)."""
    _, _, det, rec = tai_model()
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    with _khoa:
        polys = det.predict(bgr, batch_size=1)[0].json["res"]["dt_polys"]
        if len(polys) == 0:
            return [], 0.0, 0
        outs = rec.predict([crop_line(bgr, p) for p in polys], batch_size=16)
    texts = [o.json["res"]["rec_text"] for o in outs]
    diem = float(np.mean([o.json["res"]["rec_score"] for o in outs]))
    return group_rows(texts, polys), diem, len(polys)
