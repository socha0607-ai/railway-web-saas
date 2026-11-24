import io
import os
import base64
import requests
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

# Safeguard against decompression bomb errors on large 360 equirectangular panoramas
Image.MAX_IMAGE_PIXELS = 150_000_000

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MB cap

app = FastAPI(
    title="WebP & 360 Optimizer API",
    description="Ultra-Fast WebP & 360° Panorama Optimizer API",
    version="1.0.0"
)

# Custom exception handlers to guarantee clean JSON errors without stack traces
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_msg = "; ".join([f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in errors])
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "Unprocessable Entity", "detail": error_msg}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTP Error", "detail": detail}
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Bad Request", "detail": "An error occurred while processing the request."}
    )


class OptimizeRequest(BaseModel):
    image_url: str = Field(..., description="Publicly accessible URL of the image to optimize")
    quality: int = Field(default=80, ge=1, le=100, description="WebP compression quality (1-100)")
    max_width: int = Field(default=4096, gt=0, description="Max width to resize proportionally (e.g. 4096 for 4K)")
    strip_metadata: bool = Field(default=True, description="Whether to strip EXIF and other metadata")


def verify_authentication(x_rapidapi_proxy_secret: Optional[str], x_api_key: Optional[str]):
    disable_auth = os.getenv("DISABLE_AUTH", "true").strip().lower() in ("true", "1", "yes")
    if disable_auth:
        return

    expected_rapidapi_secret = os.getenv("RAPIDAPI_PROXY_SECRET")
    expected_api_key = os.getenv("API_KEY")

    authorized = False
    if expected_rapidapi_secret and x_rapidapi_proxy_secret == expected_rapidapi_secret:
        authorized = True
    elif expected_api_key and x_api_key == expected_api_key:
        authorized = True

    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid API key / RapidAPI proxy secret"
        )


@app.get("/")
def health_check():
    return {
        "status": "live",
        "engine": "WebP-360-Optimizer",
        "version": "1.0.0"
    }


@app.post("/optimize")
def optimize_image(
    payload: OptimizeRequest,
    x_rapidapi_proxy_secret: Optional[str] = Header(None, alias="X-RapidAPI-Proxy-Secret"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    verify_authentication(x_rapidapi_proxy_secret, x_api_key)

    # Validate image URL
    parsed_url = urlparse(payload.image_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image_url. Only http and https protocols are supported."
        )

    # Download image with streaming and 25MB cap
    try:
        req_headers = {"User-Agent": "WebP-360-Optimizer/1.0"}
        with requests.get(payload.image_url, stream=True, timeout=15, headers=req_headers) as response:
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch image from URL. Upstream server returned HTTP {response.status_code}."
                )

            # Check Content-Length header if provided
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_DOWNLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image size ({int(content_length)} bytes) exceeds the 25MB limit."
                )

            # Stream download to enforce limit
            chunks = []
            downloaded_bytes = 0
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Downloaded image exceeded the 25MB limit."
                        )
                    chunks.append(chunk)

            raw_bytes = b"".join(chunks)

            if len(raw_bytes) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Fetched image is empty."
                )

    except HTTPException:
        raise
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Network error while fetching image: {str(e)}"
        )

    # Open image with Pillow
    try:
        image = Image.open(io.BytesIO(raw_bytes))
    except (UnidentifiedImageError, Exception):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provided URL does not point to a recognized or valid image format."
        )

    try:
        # Respect orientation tag if present before stripping
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    # Convert RGBA/P modes to RGB cleanly
    try:
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        # Resize proportionally if width > max_width
        if image.width > payload.max_width:
            ratio = payload.max_width / float(image.width)
            new_height = max(1, int(round(image.height * ratio)))
            image = image.resize((payload.max_width, new_height), Image.Resampling.LANCZOS)

        # Compress to WEBP (method=6)
        output_io = io.BytesIO()
        save_kwargs: Dict[str, Any] = {
            "format": "WEBP",
            "quality": payload.quality,
            "method": 6
        }

        if not payload.strip_metadata and "exif" in image.info:
            save_kwargs["exif"] = image.info["exif"]

        image.save(output_io, **save_kwargs)
        optimized_bytes = output_io.getvalue()

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image processing failed: {str(e)}"
        )

    original_kb = round(len(raw_bytes) / 1024, 2)
    optimized_kb = round(len(optimized_bytes) / 1024, 2)
    if len(raw_bytes) > 0:
        savings_percent = round(max(0.0, (1.0 - (len(optimized_bytes) / len(raw_bytes))) * 100.0), 2)
    else:
        savings_percent = 0.0

    return {
        "original_kb": original_kb,
        "optimized_kb": optimized_kb,
        "savings_percent": savings_percent,
        "dimensions": {
            "width": image.width,
            "height": image.height
        },
        "webp_base64": base64.b64encode(optimized_bytes).decode("utf-8")
    }
