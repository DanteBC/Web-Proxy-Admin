# Web Proxy Admin

FastAPI administration service for 3proxy and Linux policy routing.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]' 
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Production

The application must run as a dedicated account. Privileged routing operations should be executed through a tightly constrained helper or systemd unit. The 3proxy reload operation requires `systemctl` access.
