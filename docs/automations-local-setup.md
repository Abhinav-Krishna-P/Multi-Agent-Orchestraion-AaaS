# Automations on your own computer

Schedules and "watch for new items" automations work as soon as the backend runs. Automations that start
on an app event (a new GitHub issue, for example) need Composio to reach your backend, so you open a
temporary tunnel to it.

1. Install the tunnel tool once (Windows): `winget install --id Cloudflare.cloudflared`
2. Start the backend, then in another terminal: `cloudflared tunnel --url http://localhost:8000`
3. Copy the address it prints, like `https://something.trycloudflare.com`. It changes every session.
4. In a terminal in `backend/`:
   - The first time ever: `.venv\Scripts\python -m app.automations.webhook_setup create <address>`, then restart the backend.
   - Every later session: `.venv\Scripts\python -m app.automations.webhook_setup update <address>`

`create` saves the webhook secret and id in `backend/.env`; it never prints the secret. If `create` says the
webhook already exists, use `update`.
