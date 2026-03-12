from io import BytesIO
from fastapi import APIRouter
from fastapi.responses import Response
from PIL import ImageGrab

router = APIRouter()


@router.get("/api/screenshot")
def screenshot():
    img = ImageGrab.grab()
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return Response(content=buf.getvalue(), media_type="image/jpeg")
