from pathlib import Path
from fastapi.templating import Jinja2Templates
from .config import load_settings
from .deps import user_perms
from .models import AuditLog
from .timeutil import aware

import time

settings = load_settings()
ASSET_V = str(int(time.time()))
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def render(request, name, user, status=200, **ctx):
    ctx.update(site_name=settings.site_name, user=user, allow_reg=settings.allow_registration, asset_v=ASSET_V,
               is_admin=bool(user and "admin.access" in user_perms(user)), msg=request.query_params.get("msg", ""))
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def audit(db, user, action, target="", detail="", request=None):
    db.add(AuditLog(user_id=user.id if user else None, action=action, target=str(target)[:128], detail=str(detail)[:2000],
                    ip=request.client.host if request and request.client else ""))


templates.env.filters["utc_iso"] = lambda d: aware(d).isoformat() if d else ""
templates.env.filters["duration_min"] = lambda c: int((aware(c.end_at) - aware(c.start_at)).total_seconds() // 60)
