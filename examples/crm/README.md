# VibeCRM Example

Run:
```bash
python3 -m vibeweb run examples/crm/crm.vweb.json --host 127.0.0.1 --port 8000
```
Admin UI: `http://127.0.0.1:8000/admin` (default `admin` / `admin`)

Security (recommended):
```bash
export VIBEWEB_ADMIN_USER="your_admin"
export VIBEWEB_ADMIN_PASSWORD="strong_password"
export VIBEWEB_API_KEY="change_me"
export VIBEWEB_RATE_LIMIT=120
export VIBEWEB_MAX_BODY_BYTES=1048576
export VIBEWEB_AUDIT_LOG=".logs/vibeweb-audit.log"
```

Quick API test:
```bash
curl -H "X-API-Key: change_me" http://127.0.0.1:8000/api/Account
```
