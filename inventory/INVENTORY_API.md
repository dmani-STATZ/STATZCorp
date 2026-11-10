# STATZWeb Inventory API — consumer contract (v1)

Read-only JSON API for `statzcorp-com` to display STATZ inventory. Server-to-server only: no CORS, never call it from a browser. Only items staff have marked **Show on public website** are returned.

## Environment variables

| Name | Where | Purpose |
|---|---|---|
| `INVENTORY_API_KEY` | STATZWeb and statzcorp-com | Sent as `X-API-Key` |
| `INVENTORY_API_HMAC_SECRET` | STATZWeb and statzcorp-com | HMAC-SHA256 signing secret |

These are separate from the supplier portal secrets. If either is unset on STATZWeb, every request returns 401.

## Signing (same recipe as the supplier portal API)

Headers on every request:

- `X-API-Key`: the API key
- `X-Timestamp`: Unix epoch seconds (integer). Must be within ±300 seconds of server time.
- `X-Signature`: lowercase hex HMAC-SHA256 of the canonical string, keyed with the secret

Canonical string (`\n` separated, no trailing newline):

```
{METHOD}\n{path}\n{timestamp}\n{body}
```

- `METHOD`: uppercase (`GET`)
- `path`: request path **without** the query string, e.g. `/api/inventory/v1/items/`
- `timestamp`: the exact `X-Timestamp` value
- `body`: empty string for GET

Python example:

```python
import hashlib, hmac, time, requests

path = "/api/inventory/v1/items/"
ts = str(int(time.time()))
canonical = f"GET\n{path}\n{ts}\n"
sig = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
resp = requests.get(
    BASE_URL + path,
    params={"q": "bolt", "page": 1},
    headers={"X-API-Key": API_KEY, "X-Timestamp": ts, "X-Signature": sig},
    timeout=10,
)
```

## Endpoints

### `GET /api/inventory/v1/items/`

| Param | Type | Default | Notes |
|---|---|---|---|
| `q` | string | — | Search NSN (dash-agnostic), description, part number, manufacturer |
| `nsn` | string | — | Exact NSN match, with or without dashes |
| `in_stock` | `true` | — | `true` → only items with an on-hand quantity > 0 |
| `page` | int ≥ 1 | 1 | Pages past the end return an empty `results` list |
| `page_size` | int ≥ 1 | 50 | Clamped to 200 |

Response `200`:

```json
{
  "count": 123,
  "page": 1,
  "page_size": 50,
  "num_pages": 3,
  "results": [
    {"id": 42, "nsn": "5305-01-234-5678", "description": "Hex bolt", "part_number": "PN-1", "manufacturer": "Acme", "quantity": 5}
  ]
}
```

Results are ordered by `nsn`, then `id`, with blank-NSN items last, so rows with the same NSN are adjacent. The order is stable across pages.

**NSN is not unique.** Each row is a separate lot (for example the same part bought at different prices), so one NSN can appear on several results with different `id`s. Use `id` as the key; sum `quantity` across rows if you need a per-NSN total.

### `GET /api/inventory/v1/items/<id>/`

Response `200`: a single item object (same shape as a `results` entry).

## Item fields

| Key | Type | Notes |
|---|---|---|
| `id` | int | Stable STATZWeb id |
| `nsn` | string | `""` when unknown. Not unique (see above) |
| `description` | string | `""` when unknown |
| `part_number` | string | `""` when unknown |
| `manufacturer` | string | `""` when unknown |
| `quantity` | int | Quantity **on hand** for this lot (what is left of a bulk lot that is drawn down over time, otherwise the stocked quantity). `0` when unknown |

No pricing, cost, or location data is ever returned.

## Errors

| Status | Body | When |
|---|---|---|
| 400 | `{"error": "invalid_parameter"}` | `page` / `page_size` not a positive integer |
| 401 | `{"error": {"code": "unauthorized", "message": "..."}}` | Missing/wrong key, bad signature, stale timestamp, or API not configured |
| 404 | `{"error": "not_found"}` | Item missing or not public |
| 405 | `{"error": "method_not_allowed"}` | Any method other than GET (checked after auth) |

Every response has `Cache-Control: no-store`. Do your own caching on the statzcorp-com side if needed.
