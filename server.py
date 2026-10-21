"""Web API: FastAPI phục vụ trang web và các endpoint.

  GET  /                  trang web kéo thả ảnh (static/index.html)
  GET  /examples/...      6 ảnh mẫu
  POST /api/hoa-don       gửi một ảnh, nhận kết quả JSON. Máy có key AWS thì bật fallback
  GET  /api/thong-ke      thống kê 200 hoá đơn gần nhất cho bảng monitoring
  GET  /metrics           metric Prometheus
  GET  /healthz           health check

Chạy trên máy:   uvicorn server:app --port 7860
"""
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import aws
import giam_sat
import mo_hinh
import pipeline

TOI_DA_MB = 10
DINH_DANG = ["JPEG", "PNG", "WEBP"]   # chỉ mở 3 định dạng ảnh chụp, không mở TIFF, PSD, EPS...
Image.MAX_IMAGE_PIXELS = 40_000_000   # ảnh 40 triệu điểm ảnh trở lên bị từ chối (decompression bomb)
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    mo_hinh.tai_model()   # tải 1,5 GB model trước khi nhận request, để người đầu tiên không phải chờ
    giam_sat.log("khoi_dong", co_key_aws=aws.co_key(), aws_moi_ngay=aws.han_muc.moi_ngay)
    yield


app = FastAPI(title="Ảnh hoá đơn vào, sổ chi tiêu ra", lifespan=lifespan)
app.mount("/examples", StaticFiles(directory=Path(__file__).parent / "examples"), name="examples")


@app.get("/", include_in_schema=False)
def trang_chu():
    return FileResponse(STATIC / "index.html")


@app.post("/api/hoa-don")
def nhan_hoa_don(anh: UploadFile = File(...)):
    """def thường (không async): FastAPI chạy hàm trong threadpool, model chạy lâu không chặn request khác."""
    du_lieu = anh.file.read(TOI_DA_MB * 1024 * 1024 + 1)
    if len(du_lieu) > TOI_DA_MB * 1024 * 1024:
        raise HTTPException(413, f"Ảnh lớn hơn {TOI_DA_MB} MB")
    try:
        img = Image.open(io.BytesIO(du_lieu), formats=DINH_DANG)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(415, "File không phải ảnh JPEG, PNG hay WEBP, hoặc ảnh quá lớn")
    try:
        return pipeline.xu_ly(img, cho_phep_aws=aws.co_key())
    except Exception as e:
        giam_sat.ghi_loi(repr(e))
        raise HTTPException(500, "App gặp lỗi khi xử lý ảnh này, đã ghi log")


@app.get("/api/thong-ke")
def thong_ke():
    return {**giam_sat.thong_ke(), "aws_con_lai_hom_nay": aws.han_muc.con_lai(), "co_key_aws": aws.co_key()}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
