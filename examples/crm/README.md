# VibeCRM Example

Run:
```bash
python3 -m vibeweb run examples/crm/crm.vweb.json --host 127.0.0.1 --port 8000
```
Admin UI: `http://127.0.0.1:8000/admin` (default `admin` / `admin`)

Advanced (actions + hooks + LLM writeback):
```bash
python3 -m vibeweb run examples/crm/crm.advanced.vweb.json --host 127.0.0.1 --port 8000
```
Notes:
- `Deal.summary` is auto-generated after create and after update (only when key fields changed).
- When a `Deal` moves to `Closed Won` and `amount > 0`, a multi-step `flow` runs:
  - Create an `Invoice`
  - Create a follow-up `Task`
  - Create a `Note`

## AI Configuration

This example includes an LLM writeback action (`Deal.summary`).
VibeWeb uses an OpenAI-compatible API by default (recommended: local GLM-4.7-Flash).

Local (recommended: GLM-4.7-Flash via llama.cpp server):
```bash
bash scripts/run_glm47_server.sh

export VIBEWEB_AI_BASE_URL="http://127.0.0.1:8080/v1"
export VIBEWEB_AI_MODEL="glm-4.7-flash"
# export VIBEWEB_AI_API_KEY="..."  # only if your local server requires it
```

Cloud option (DeepSeek):
```bash
export VIBEWEB_AI_BASE_URL="https://api.deepseek.com/v1"
export VIBEWEB_AI_MODEL="deepseek-chat"
export VIBEWEB_AI_API_KEY="your_deepseek_key"
```

## Security (Recommended Baseline)

```bash
export VIBEWEB_ADMIN_USER="your_admin"
export VIBEWEB_ADMIN_PASSWORD="strong_password"
export VIBEWEB_API_KEY="change_me"
export VIBEWEB_RATE_LIMIT=120
export VIBEWEB_MAX_BODY_BYTES=1048576
export VIBEWEB_AUDIT_LOG=".logs/vibeweb-audit.log"

# Outbound HTTP/LLM policy:
# - `http://...` is only allowed for localhost.
# - `https://...` requires an explicit host allowlist.
# - The host from `VIBEWEB_AI_BASE_URL` is automatically allowed.
# Add extra hosts only when you really need them (principle of least privilege).
export VIBEWEB_OUTBOUND_ALLOW_HOSTS="example.com"

# Optional: used by the advanced CRM spec if you enable webhook actions.
export VIBEWEB_WEBHOOK_URL="https://example.com/webhook"
```

Quick API test:
```bash
curl -H "X-API-Key: change_me" http://127.0.0.1:8000/api/Account
```
