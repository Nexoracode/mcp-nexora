# nexora – MySQL/MariaDB MCP server for ChatGPT

## Setup
```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env      # fill in DB_* and MCP_API_KEY
.venv\Scripts\python -m nexora.server     # serves http://127.0.0.1:8000/mcp
```

## Least-privilege DB user
```sql
CREATE USER 'nexora'@'%' IDENTIFIED BY '...';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER ON mydb.* TO 'nexora'@'%';
```
(no DROP / GRANT.)

## Connect ChatGPT
1. Expose the port over HTTPS: `cloudflared tunnel --url http://127.0.0.1:8000`
2. ChatGPT → Settings → Connectors → Advanced → Developer mode → Add connector,
   URL `https://<tunnel-host>/mcp`.
3. If the connector UI can't send a custom Bearer header, leave `MCP_API_KEY` empty and
   rely on an unguessable tunnel URL only for short tests (the guard still blocks DROP/TRUNCATE).

## Tools
`list_tables`, `describe_table`, `table_stats`, `run_select`, `preview_write` → `execute_write(confirm_token)`.

## Tests
`.venv\Scripts\python -m pytest`

## Nexora API tools
With `NEXORA_API_URL` and `NEXORA_API_TOKEN` set, the server also exposes tools backed by the panel's owner API
(`list_sites`, `get_site`, `update_site`, `adjust_wallet`, `approve_purchase`, `reject_purchase`, `approve_topup`,
`reject_topup`, `reply_ticket`, `close_ticket`, `update_feature`, `create_package`, ...). Every mutating tool needs
`confirm=true`; without it the tool only returns a preview with the current state. Raw SQL writes
(`preview_write` / `execute_write`) are off unless `ENABLE_SQL_WRITE=true`. Reads via `run_select` stay available,
so give the database user `SELECT` only.
