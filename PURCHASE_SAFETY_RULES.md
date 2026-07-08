Absolutely. This version is **laser-focused** exclusively on the **purchase flow** and preventing accidental real API calls. 

It is stripped down, written in plain English for any AI agent (OpenCode, Cursor, Copilot, etc.), and contains only the critical safety commands.

**Save this file as:** `PURCHASE_SAFETY_RULES.md` (Place it in the root of your project).

---

```markdown
# 🔒 PURCHASE FLOW SAFETY RULES (Real API Protection)

**WARNING:** Breaking these rules creates **REAL SUBSCRIPTIONS** on the provider's server (NEO 4K, HotPlayer, etc.) and **CONSUMES REAL MONEY**. 

---

## 🎯 THE GOLDEN RULE (For Purchase Code)

**NEVER IMPORT A REAL PROVIDER DIRECTLY IN THE PURCHASE FLOW.**

- ❌ **BANNED:** `from api.providers.cms_only import CMSOnlyAdapter` inside `services.py`, `views.py`, or any test script that triggers a purchase.
- ✅ **REQUIRED:** `from api.providers import get_provider_adapter` and call `get_provider_adapter()`.

**The Factory (`get_provider_adapter`) is the ONLY safe way to get an adapter. It checks the `.env` file for `USE_MOCK_PROVIDER`. Hardcoding bypasses this check and WILL cost you money.**

---

## 🧪 MOCK vs. REAL (The Safety Switch)

| Mode | `.env` Setting | DNS in Receipt | Cost |
|------|----------------|----------------|------|
| **Safe Mode (Testing)** | `USE_MOCK_PROVIDER=True` | `mock-cdn.me` | **$0.00** |
| **Danger Mode (Production)** | `USE_MOCK_PROVIDER=False` | `neo-cdn1.me` or `hotplayer.app` | **Real Credits** |

**RULE:** Before writing any purchase-related code, confirm you are in Safe Mode by checking the receipt DNS. If it says `mock-cdn.me`, you are safe. If it says `neo-cdn1.me`, you are spending money.

---

## 🔍 MANDATORY VERIFICATION (Before any test)

**Always run this check BEFORE running a purchase test:**

```bash
docker-compose exec backend python -c "import os; print(os.getenv('USE_MOCK_PROVIDER'))"
```

- ✅ **Output `True`:** Proceed with testing. You are safe.
- ❌ **Output `False` or `None`:** **STOP.** Do NOT buy. The real API will be called. Fix your `.env` and restart.

---

## 🐳 THE DOCKER RESTART RULE

**Do NOT rely on `docker-compose restart` to apply `.env` changes.** It does NOT reload environment variables.

**The ONLY safe restart procedure:**

```bash
docker-compose down   # Kills the container completely
docker-compose up -d  # Rebuilds with the new .env
```

---

## 🧪 SAFE TESTING PROTOCOL (If you MUST test the real API)

1. Set `USE_MOCK_PROVIDER=False` in `.env`.
2. Run `docker-compose down && docker-compose up -d`.
3. **Buy exactly qty=1** of the cheapest product.
4. Check the receipt.
5. **IMMEDIATELY** switch back to `USE_MOCK_PROVIDER=True`.
6. Run `docker-compose down && docker-compose up -d` again.

**This limits financial damage to a maximum of 1 credit.**

---

## 💸 EMERGENCY STOP (If you accidentally created real lines)

If you see real credentials (e.g., `calvin56816.neo-cdn1.me`) in your receipt during testing:

1. **Go to Django Admin** → **Credentials**.
2. Select the newly created lines.
3. Use the **"Toggle revoke"** action to disable them immediately.
4. **Go to Django Admin** → **Quarantined credentials**.
5. Mark them as **"Resolved"**.
6. Contact your provider with the `external_username` (numeric IDs) and ask them to delete these test lines.

---

## 🚫 BANNED PATTERNS (Never write this code)

```python
# 🚨 DANGEROUS - WILL SPEND REAL MONEY
from api.providers.cms_only import CMSOnlyAdapter
adapter = CMSOnlyAdapter()
result = adapter.create_line(pack_id=123, months=1)
```

```python
# ✅ SAFE - Respects the .env file
from api.providers import get_provider_adapter
adapter = get_provider_adapter()
result = adapter.create_line(pack_id=123, months=1)
```

---

## ✅ AGENT CHECKLIST (Before writing purchase code)

- [ ] I have verified `USE_MOCK_PROVIDER=True` is active in the container.
- [ ] My new code uses `get_provider_adapter()`, NOT the real adapter directly.
- [ ] I am NOT writing any test scripts that hardcode the real adapter.
- [ ] I understand that violating these rules will cost real money and waste provider credits.

---

**If in doubt about the purchase flow, ASK before coding. A 5-minute question is cheaper than a 50-credit mistake.**
``` 