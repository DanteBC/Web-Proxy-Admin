from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router as routes_router
from app.api.statistics import router as statistics_router
from app.api.users import router as users_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.security import verify_password
from app.services.ldap import authenticate as ldap_authenticate

Base.metadata.create_all(engine)

app = FastAPI(title="Web Proxy Admin")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def require_api_session(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Unauthorized")


api_dependencies = [Depends(require_api_session)]
app.include_router(users_router, dependencies=api_dependencies)
app.include_router(routes_router, dependencies=api_dependencies)
app.include_router(statistics_router, dependencies=api_dependencies)


@app.post("/login", include_in_schema=False)
async def login_form(request: Request):
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))

    local_password_hash = None
    try:
        # Local credentials are optionally encoded as PBKDF2 through the app settings.
        from app.core.security import hash_password
        local_password_hash = getattr(app.state, "admin_password_hash", None)
        if local_password_hash is None:
            app.state.admin_password_hash = hash_password(settings.admin_password)
            local_password_hash = app.state.admin_password_hash
    except Exception:
        pass

    valid = (
        username == settings.admin_login
        and local_password_hash is not None
        and verify_password(password, local_password_hash)
    ) or ldap_authenticate(username, password)

    if not valid:
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"}, status_code=401)

    request.session["authenticated"] = True
    request.session["username"] = username
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", {"username": request.session.get("username")})
