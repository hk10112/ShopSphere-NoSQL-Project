# Individual Modification Challenge — Reference Solutions

This document contains a working approach (with code) for **each** of the six
suggested scenarios, so whichever one is assigned can be implemented quickly.

---

## 📊 Scenario A — Atomic Counters for the Average Rating

**Problem:** the average is computed by fetching *all* reviews on every page load.

**Fix:** store `rating_sum` and `review_count` on the product item and update
them atomically with `ADD` whenever a review is posted. The average becomes a
single `GetItem` — O(1) regardless of the number of reviews.

```python
# db.py — inside add_review(), after the review PutItem:
table.update_item(
    Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"},
    UpdateExpression="ADD rating_sum :r, review_count :one",
    ExpressionAttributeValues={":r": int(rating), ":one": 1},
)

# Reading the average (no review fetch needed):
def get_average_rating_fast(product):
    count = int(product.get("review_count", 0))
    if count == 0:
        return None
    return round(int(product["rating_sum"]) / count, 1)
```

Notes for the README/video: `ADD` is **atomic** — concurrent reviews can't
produce a lost update. Also initialize/backfill existing products once with a
small migration script that Queries each product's reviews and sets the two
counters.

---

## 🔍 Scenario B — GSI Instead of Scan for the Category Filter

*(Already implemented in the base project — `CategoryIndex` GSI.)*

If starting from a Scan version, the change is:

```python
# BEFORE (reads the whole table, filter applied AFTER the read):
resp = table.scan(FilterExpression=Attr("category").eq(category))

# AFTER (reads only matching items):
resp = table.query(
    IndexName="CategoryIndex",
    KeyConditionExpression=Key("GSI1PK").eq(f"CATEGORY#{category}"),
)
```

Adding the GSI to an existing table (no downtime):

```python
dynamodb.update_table(
    TableName="ShopSphere",
    AttributeDefinitions=[
        {"AttributeName": "GSI1PK", "AttributeType": "S"},
        {"AttributeName": "GSI1SK", "AttributeType": "S"},
    ],
    GlobalSecondaryIndexUpdates=[{
        "Create": {
            "IndexName": "CategoryIndex",
            "KeySchema": [
                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    }],
)
```

Cost difference to document: a Scan bills RCUs for **every item read**, even
those the filter rejects; the GSI Query bills only for items in the category
(see README §3 for the worked 100k-item example).

---

## 📲 Scenario C — Native Pagination with LastEvaluatedKey

```python
# db.py
import base64, json

def list_products_page(limit=12, start_key_token=None):
    kwargs = {
        "FilterExpression": Attr("entity_type").eq("PRODUCT"),
        "Limit": limit,
    }
    if start_key_token:
        kwargs["ExclusiveStartKey"] = json.loads(
            base64.urlsafe_b64decode(start_key_token).decode()
        )
    resp = table.scan(**kwargs)
    next_token = None
    if "LastEvaluatedKey" in resp:
        next_token = base64.urlsafe_b64encode(
            json.dumps(resp["LastEvaluatedKey"]).encode()
        ).decode()
    return resp.get("Items", []), next_token
```

```python
# app.py
@app.route("/")
def index():
    token = request.args.get("page_token")
    products, next_token = db.list_products_page(limit=12, start_key_token=token)
    return render_template("index.html", products=products, next_token=next_token)
```

```html
<!-- index.html -->
{% if next_token %}
  <a class="btn" href="{{ url_for('index', page_token=next_token) }}">Next →</a>
{% else %}
  <span class="hint">No more pages.</span>
{% endif %}
```

Implementation notes:
* The `LastEvaluatedKey` dict is base64-encoded so it can travel safely in a URL.
* DynamoDB pagination is **forward-only**; for a real "Previous" button keep a
  stack of previous tokens in the Flask session and pop it:

```python
# "Previous" support: push the current token before navigating forward
history = session.get("page_history", [])
# on Next: history.append(current_token); on Prev: token = history.pop()
session["page_history"] = history
```

* When `LastEvaluatedKey` is absent from the response, you are on the last page.

---

## 🧹 Scenario D — Soft Delete

```python
# db.py — replace delete_product() with:
def soft_delete_product(product_id):
    table.update_item(
        Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"},
        UpdateExpression="SET is_deleted = :t, updated_at = :u",
        ExpressionAttributeValues={":t": True, ":u": _now_iso()},
    )

def restore_product(product_id):
    table.update_item(
        Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"},
        UpdateExpression="SET is_deleted = :f, updated_at = :u",
        ExpressionAttributeValues={":f": False, ":u": _now_iso()},
    )
```

Filter deleted products out of every listing:

```python
# Scan-based listing:
FilterExpression=Attr("entity_type").eq("PRODUCT")
                 & (Attr("is_deleted").not_exists() | Attr("is_deleted").eq(False))

# GSI Query (key condition can't filter non-key attrs, so add a FilterExpression):
table.query(
    IndexName="CategoryIndex",
    KeyConditionExpression=Key("GSI1PK").eq(f"CATEGORY#{category}"),
    FilterExpression=Attr("is_deleted").not_exists() | Attr("is_deleted").eq(False),
)
```

Hidden admin view:

```python
@app.route("/admin/deleted")
def admin_deleted():
    items = [p for p in db.list_all_products_including_deleted()
             if p.get("is_deleted")]
    return render_template("admin_deleted.html", products=items)

@app.route("/admin/restore/<product_id>", methods=["POST"])
def admin_restore(product_id):
    db.restore_product(product_id)
    flash("Product restored.", "success")
    return redirect(url_for("admin_deleted"))
```

Audit-trail bonus: reviews are never touched, so the full history survives.

---

## 🕓 Scenario E — created_at / updated_at + "Newest First" GSI

The base project already writes ISO-8601 `created_at`/`updated_at` on products
and `created_at` on reviews. What this scenario adds is a **GSI sorted by
`updated_at`**:

```python
# create_table.py — extra GSI (note: a GSI partition key must have a value
# shared by the items you want to sort together, so use a constant for products)
{
    "IndexName": "NewestIndex",
    "KeySchema": [
        {"AttributeName": "GSI2PK", "KeyType": "HASH"},   # constant: "PRODUCT"
        {"AttributeName": "updated_at", "KeyType": "RANGE"},
    ],
    "Projection": {"ProjectionType": "ALL"},
}
```

```python
# On every product write, also set:
"GSI2PK": "PRODUCT",          # same value for all products
"updated_at": _now_iso(),     # ISO-8601 strings sort chronologically

# Newest-first listing — a Query, not a Scan, and pre-sorted by DynamoDB:
def list_products_newest():
    resp = table.query(
        IndexName="NewestIndex",
        KeyConditionExpression=Key("GSI2PK").eq("PRODUCT"),
        ScanIndexForward=False,   # descending = newest first
    )
    return resp.get("Items", [])
```

Mention in the video: ISO-8601 UTC strings sort lexicographically in the same
order as chronologically — that's exactly why the format was chosen. (Caveat
worth stating: a single constant partition key concentrates the GSI in one
partition; fine for tens of thousands of products, shard the key —
`PRODUCT#0..N` — if it ever becomes a hot partition.)

---

## 🚫 Scenario F — Prevent Duplicate Reviews (ConditionExpression)

The trick: make the review key **deterministic per (product, customer)** so a
condition on the key can detect duplicates. Move the timestamp out of the SK
and into a normal attribute:

```python
# db.py
from botocore.exceptions import ClientError

class DuplicateReviewError(Exception):
    pass

def add_review_unique(product_id, customer_name, rating, comment):
    now = _now_iso()
    try:
        table.put_item(
            Item={
                "PK": f"PRODUCT#{product_id}",
                "SK": f"REVIEW#{customer_name.strip().lower()}",  # deterministic
                "entity_type": "REVIEW",
                "product_id": product_id,
                "customer_name": customer_name,
                "rating": int(rating),
                "comment": comment,
                "created_at": now,
            },
            # Fail if an item with this exact PK+SK already exists
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise DuplicateReviewError(
                f"{customer_name} has already reviewed this product."
            )
        raise
```

```python
# app.py
try:
    db.add_review_unique(product_id, customer_name, rating_val, comment)
    flash("Thank you! Your review was submitted.", "success")
except db.DuplicateReviewError as e:
    flash(str(e), "error")
```

Why it works: `PutItem` with `attribute_not_exists(PK)` is evaluated
**atomically on the server** — there is no race window between "check" and
"write", unlike a read-then-write approach. Sorting by date still works because
`created_at` remains stored as an attribute (sort in Python after the Query).
