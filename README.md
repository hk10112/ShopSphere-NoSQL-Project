# 🛍️ ShopSphere — Product Catalog & Customer Feedback Platform

Final project for **NoSQL & Information Storage** (Dr. Mossab).
A cloud-native product catalog built with **Python 3.10+, Flask 3.x, and AWS DynamoDB (boto3)**.

Vendors can list products; customers can browse the catalog, filter by category,
submit reviews (1–5 stars), and see the live average rating per product.

---

## 1. Features

| Area | Implemented |
|------|-------------|
| Product CRUD | Add (`PutItem`), list (`Scan` / GSI `Query`), detail (`GetItem`), update (`UpdateItem`), delete (`DeleteItem` via batch) |
| Category filter | **GSI Query** on `CategoryIndex` — no full-table Scan |
| Reviews | Submit (composite-key `PutItem`), display (`Query` with `begins_with`), average rating, sort by **date** or **rating** |
| Validation | All forms validated server-side; friendly flash messages |
| Edge cases | Empty catalog, product with no reviews, invalid product ID — all handled |

---

## 2. DynamoDB Schema Design (Single-Table)

**Table name:** `ShopSphere` · **Billing:** `PAY_PER_REQUEST` (on-demand)

### 2.1 Key design

| Entity | PK | SK | Notes |
|--------|----|----|-------|
| Product | `PRODUCT#<uuid>` | `METADATA` | One item per product |
| Review | `PRODUCT#<uuid>` | `REVIEW#<ISO-timestamp>#<customer>` | Lives in the **same partition** as its product |

### 2.2 Global Secondary Index — `CategoryIndex`

| | Attribute | Value example |
|--|-----------|---------------|
| GSI Partition Key | `GSI1PK` | `CATEGORY#Electronics` |
| GSI Sort Key | `GSI1SK` | `PRODUCT#<uuid>` |
| Projection | `ALL` | |

Only **product** items carry `GSI1PK`/`GSI1SK`, so reviews are automatically
excluded from the index (sparse index pattern).

### 2.3 Example items

```json
{ "PK": "PRODUCT#a1b2", "SK": "METADATA",
  "entity_type": "PRODUCT", "product_id": "a1b2",
  "name": "Wireless Mouse", "category": "Electronics",
  "price": 14.99, "stock": 120, "image_url": "...",
  "created_at": "2026-06-08T10:00:00Z", "updated_at": "2026-06-08T10:00:00Z",
  "GSI1PK": "CATEGORY#Electronics", "GSI1SK": "PRODUCT#a1b2" }

{ "PK": "PRODUCT#a1b2", "SK": "REVIEW#2026-06-08T12:30:00Z#Ahmad",
  "entity_type": "REVIEW", "customer_name": "Ahmad",
  "rating": 5, "comment": "Excellent!", "created_at": "2026-06-08T12:30:00Z" }
```

### 2.4 Access patterns → operations

| # | Access pattern | Operation |
|---|----------------|-----------|
| 1 | Get one product | `GetItem(PK=PRODUCT#id, SK=METADATA)` |
| 2 | List all products | `Scan` + filter `entity_type = PRODUCT` (acceptable for MVP-size catalog) |
| 3 | List products in a category | **`Query` on `CategoryIndex`** (`GSI1PK = CATEGORY#x`) |
| 4 | Get all reviews of a product, newest first | `Query(PK=PRODUCT#id AND begins_with(SK,'REVIEW#'))`, `ScanIndexForward=False` |
| 5 | Create / update / delete product | `PutItem` / `UpdateItem` / `DeleteItem` |
| 6 | Add review | `PutItem` with composite SK `REVIEW#<ts>#<name>` |

### 2.5 Why single-table?

* A product and its reviews share one partition key → **one `Query` returns the
  product's whole "aggregate"** with no joins and no second round-trip.
* Embedding the timestamp in the review SK means DynamoDB returns reviews
  **pre-sorted by date for free** — no in-memory sort for the default view.
* One table = one billing surface, one GSI, simpler IAM and simpler ops.
* A multi-table design (Products + Reviews) would only duplicate the same key
  structure across two tables and add a network call per page — no benefit here.

---

## 3. GSI Query vs. Full Scan — Cost & Performance

DynamoDB charges reads in **Read Capacity Units**: 1 RCU = one strongly
consistent read (or two eventually consistent reads) of up to 4 KB.

| | `Scan` + `FilterExpression` | `Query` on `CategoryIndex` |
|--|----------------------------|----------------------------|
| Items **read (and billed)** | **Every item in the table**, even non-matching ones — the filter is applied *after* the read | **Only the items in the requested category** |
| Latency | Grows linearly with table size | Stays proportional to the result size |
| 100,000 products (~1 KB each), category holds 500 | ~12,500 RCU per filter request (eventually consistent) | ~63 RCU per request — **~200× cheaper** |
| Scaling behaviour | Gets worse every day as the catalog grows | Constant relative to result set |

**Conclusion:** `FilterExpression` does *not* reduce read cost — it only reduces
the bytes returned to the client. That is why the category filter in this app
uses the `CategoryIndex` GSI (`db.list_products_by_category`). The only Scan
remaining is the unfiltered "all products" view, which is flagged as a known
trade-off (the proper fix at scale is GSI-backed pagination — see Scenario C
in `MODIFICATIONS.md`).

**Write-side cost of the GSI:** each product write is duplicated into the
index (≈2× WCU for product writes). Reviews don't carry GSI keys, so review
writes (the high-volume path) cost no extra — a deliberate sparse-index choice.

---

## 4. Setup Instructions

### 4.1 Prerequisites
* Python 3.10+
* An AWS account with an IAM user (programmatic access, `AmazonDynamoDBFullAccess` for the project scope)
  — **or** DynamoDB Local via Docker for free development

### 4.2 Install

```bash
git clone <your-repo-url>
cd shopsphere
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4.3 Configure environment

Create a `.env` file (never commit it — it is in `.gitignore`):

```env
AWS_ACCESS_KEY_ID=your_key_here
AWS_SECRET_ACCESS_KEY=your_secret_here
AWS_REGION=us-east-1
DYNAMODB_TABLE=ShopSphere
FLASK_SECRET_KEY=any-random-string

# Optional — only when using DynamoDB Local:
# DYNAMODB_ENDPOINT_URL=http://localhost:8000
```

To use DynamoDB Local instead of AWS during development:

```bash
docker run -p 8000:8000 amazon/dynamodb-local
# then uncomment DYNAMODB_ENDPOINT_URL in .env
```

### 4.4 Create the table & run

```bash
python create_table.py      # creates table + CategoryIndex GSI
python seed_data.py         # optional demo data
flask --app app run --debug # or: python app.py
```

Open http://127.0.0.1:5000

---

## 5. Project Structure

```
shopsphere/
├── app.py              # Flask routes (thin controllers)
├── db.py               # ALL DynamoDB logic (repository module)
├── create_table.py     # Table + GSI creation script
├── seed_data.py        # Optional demo data
├── templates/          # Jinja2 templates
│   ├── base.html
│   ├── index.html
│   ├── product_detail.html
│   └── product_form.html
├── static/style.css
├── requirements.txt
├── .env.example
├── .gitignore
├── MODIFICATIONS.md    # Solutions to the six modification scenarios
└── README.md
```

---

## 6. Daily Development Log

> Commit one entry at the end of each day (replace with your real notes).

* **Day 1:** Created AWS account & IAM user, designed the single-table schema
  (PK/SK + CategoryIndex GSI) and documented the access patterns above.
  Scaffolded the Flask project, connected boto3, first commit.
* **Day 2:** Implemented full product CRUD (PutItem, Scan, GetItem, UpdateItem,
  DeleteItem). Manually tested every operation through the UI.
* **Day 3:** Built the review model with composite SK `REVIEW#<ts>#<name>`,
  the submission form, the Query-based review listing, and the live average rating.
* **Day 4:** Replaced the category Scan with a Query on CategoryIndex, added
  sorting (date/rating), input validation, and edge-case handling. Wrote the
  GSI vs Scan cost comparison.
* **Day 5:** End-to-end testing, README polish with screenshots, recorded the
  walkthrough video, tagged release `v1.0`.

---

## 7. Screenshots

> Add your own screenshots here before submitting:
> `![Catalog](docs/screenshot-catalog.png)` etc.

---

## 8. Resources / Citations

* AWS DynamoDB Developer Guide — single-table design & GSIs
* boto3 documentation — DynamoDB resource API
* Flask 3.x documentation
