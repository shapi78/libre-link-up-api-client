# LibreLinkUp (LLU) – Python “Last Reading” Client (Unofficial)

This repo contains a small Python script that logs into **LibreLinkUp (LLU)** and fetches the **latest glucose reading** by calling the LLU “graph” endpoint.

> ⚠️ **Unofficial / Unsupported**
>
> This is **not** an official Abbott API or SDK. The endpoints and required headers can change at any time, and your account may be rate-limited or blocked. Use at your own risk.

---

## What this script does

1. **Login**: `POST /llu/auth/login`
2. Handles **EU redirect** (`data.redirect=true` + `data.region=eu`) by switching to:
   - `https://api-eu.libreview.io`
3. Handles **minimum version enforcement**:
   - If server returns `403` with `status=920` and `data.minimumVersion`, it updates the `version` header and retries.
4. Adds required header:
   - `account-id = sha256(<user.id from login response>)`
5. Gets a **Connection**:
   - `GET /llu/connections` (to obtain a `patientId`)
6. Fetches graph data:
   - `GET /llu/connections/{patientId}/graph`
7. Extracts the latest reading from:
   - `data.connection.glucoseMeasurement`

---

## Important concept: you must have a “Connection”

LibreLinkUp’s LLU API is designed around **sharing** (follower/caregiver model).  
If `GET /llu/connections` returns:

```json
{ "status": 0, "data": [] }

