# LibreLinkUp (LLU) – Python “Last Reading” Client (Unofficial)

This project provides a Python script that logs into **LibreLinkUp (LLU)** and fetches the **latest glucose reading** using the (unofficial) LLU API.

> ⚠️ **Unofficial / Unsupported**
>
> This is NOT an official Abbott API. All endpoints and headers are reverse-engineered and may change at any time.

---

## What this script does

The script performs the following flow:

1. **Login**
   - `POST /llu/auth/login`

2. **Region redirect handling**
   - If the response contains:
     ```json
     {"data": {"redirect": true, "region": "eu"}}
     ```
     the script switches automatically to:
     ```
     https://api-eu.libreview.io
     ```

3. **Minimum app version enforcement**
   - If the server responds with:
     ```json
     {"status": 920, "data": {"minimumVersion": "4.16.0"}}
     ```
     the script upgrades the `version` header and retries.

4. **Required header injection**
   - The script computes:
     ```
     account-id = sha256(login.data.user.id)
     ```
     and includes it in all data requests.

5. **Get connection (patient)**
   - `GET /llu/connections`

6. **Fetch glucose graph**
   - `GET /llu/connections/{patientId}/graph`

7. **Extract latest reading**
   - From:
     ```
     data.connection.glucoseMeasurement
     ```

---

## Critical concept: You MUST have a Connection

LibreLinkUp works on a **sharing model**.

If this request returns:

```json
{"status": 0, "data": []}
```

then **no one is sharing data with this account** and **no readings can be retrieved**.

---

## Sender & Follower configuration (REQUIRED)

You need **two roles**:

| Role      | App          | Purpose |
|-----------|--------------|---------|
| **Sender**    | LibreLink    | Phone connected to sensor |
| **Follower**  | LibreLinkUp  | Account used by this script |

### Step-by-step setup

#### On the Sender (LibreLink app)
1. Open **LibreLink**
2. Go to:
   ```
   Menu → Connected Apps / Share → LibreLinkUp
   ```
3. Invite the follower email address

#### On the Follower (LibreLinkUp app)
1. Open **LibreLinkUp**
2. Accept the invitation

After this, the API will return:

```json
{
  "status": 0,
  "data": [
    {"patientId": "..."}
  ]
}
```

And your Python script will finally work.

---

## Requirements

### System
- Python **3.10+**
- Internet access

### Python dependencies
```bash
pip install requests
```

Optional `requirements.txt`:

```txt
requests>=2.31.0
```

---

## Setup

Set environment variables:

```bash
export LIBRELINK_EMAIL="your_follower_email@example.com"
export LIBRELINK_PASSWORD="your_password"
```

---

## Run

```bash
python librelink_last.py
```

---

## Example Output

```
Logged in. Base URL: https://api-eu.libreview.io
Using version header: 4.16.0
Latest reading (raw): {...}
Latest: value=123 trend=Flat time=2026-01-31T10:42:00
```

---

## Disclaimer

Unofficial. Unsupported. May break at any time.
