"""
db.py — All DynamoDB logic for ShopSphere.
Flask routes stay thin; every database operation lives here.

Single-table design:
    Table: ShopSphere
    PK                  SK                          Entity
    PRODUCT#<id>        METADATA                    Product item
    PRODUCT#<id>        REVIEW#<iso-ts>#<customer>  Review item

    GSI: CategoryIndex
    GSI1PK = CATEGORY#<category>   GSI1SK = PRODUCT#<id>
    -> lets us Query products by category instead of Scanning the table.
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "ShopSphere")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
# Optional: point at DynamoDB Local during development (e.g. http://localhost:8000)
ENDPOINT_URL = os.getenv("DYNAMODB_ENDPOINT_URL") or None

_dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
    endpoint_url=ENDPOINT_URL,
)
table = _dynamodb.Table(TABLE_NAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def create_product(name, description, category, price, stock, image_url=""):
    """PutItem — create a new product."""
    product_id = str(uuid.uuid4())
    now = _now_iso()
    item = {
        "PK": f"PRODUCT#{product_id}",
        "SK": "METADATA",
        "entity_type": "PRODUCT",
        "product_id": product_id,
        "name": name,
        "description": description,
        "category": category,
        "price": Decimal(str(price)),
        "stock": int(stock),
        "image_url": image_url,
        "created_at": now,
        "updated_at": now,
        # GSI attributes for category-based Query
        "GSI1PK": f"CATEGORY#{category}",
        "GSI1SK": f"PRODUCT#{product_id}",
    }
    table.put_item(Item=item)
    return product_id


def get_product(product_id):
    """GetItem — fetch one product by its key."""
    resp = table.get_item(Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"})
    return resp.get("Item")


def list_products():
    """
    Scan with a FilterExpression on entity_type.
    NOTE: acceptable for the 'view all' page on a small catalog;
    category filtering deliberately uses the GSI Query below instead.
    """
    resp = table.scan(FilterExpression=Attr("entity_type").eq("PRODUCT"))
    items = resp.get("Items", [])
    # Handle pagination of Scan results (Scan returns max 1 MB per call)
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            FilterExpression=Attr("entity_type").eq("PRODUCT"),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


def list_products_by_category(category):
    """
    Query on the CategoryIndex GSI — reads ONLY items in that category.
    This is the efficient alternative to Scan + FilterExpression.
    """
    resp = table.query(
        IndexName="CategoryIndex",
        KeyConditionExpression=Key("GSI1PK").eq(f"CATEGORY#{category}"),
    )
    return resp.get("Items", [])


def update_product(product_id, name, description, category, price, stock, image_url=""):
    """UpdateItem — update product attributes (and keep GSI keys in sync)."""
    table.update_item(
        Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"},
        UpdateExpression=(
            "SET #n = :n, description = :d, category = :c, price = :p, "
            "stock = :s, image_url = :i, updated_at = :u, "
            "GSI1PK = :gpk, GSI1SK = :gsk"
        ),
        ExpressionAttributeNames={"#n": "name"},  # 'name' is a reserved word
        ExpressionAttributeValues={
            ":n": name,
            ":d": description,
            ":c": category,
            ":p": Decimal(str(price)),
            ":s": int(stock),
            ":i": image_url,
            ":u": _now_iso(),
            ":gpk": f"CATEGORY#{category}",
            ":gsk": f"PRODUCT#{product_id}",
        },
    )


def delete_product(product_id):
    """DeleteItem — remove the product and all of its reviews."""
    # Delete reviews first (Query the partition, then batch delete)
    reviews = get_reviews(product_id)
    with table.batch_writer() as batch:
        for r in reviews:
            batch.delete_item(Key={"PK": r["PK"], "SK": r["SK"]})
        batch.delete_item(Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"})


def get_all_categories():
    """Distinct categories from the current catalog (for the filter dropdown)."""
    return sorted({p.get("category", "") for p in list_products() if p.get("category")})


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

def add_review(product_id, customer_name, rating, comment):
    """
    PutItem with a composite sort key: REVIEW#<timestamp>#<customer>.
    Storing the timestamp in the SK means a Query returns reviews
    already sorted by date (newest first with ScanIndexForward=False).
    """
    now = _now_iso()
    item = {
        "PK": f"PRODUCT#{product_id}",
        "SK": f"REVIEW#{now}#{customer_name}",
        "entity_type": "REVIEW",
        "product_id": product_id,
        "customer_name": customer_name,
        "rating": int(rating),
        "comment": comment,
        "created_at": now,
    }
    table.put_item(Item=item)


def get_reviews(product_id, sort_by="date"):
    """
    Query — fetch all reviews for one product using
    PK = PRODUCT#<id> AND begins_with(SK, 'REVIEW#').
    Newest first by default (timestamp is embedded in the SK).
    """
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"PRODUCT#{product_id}")
            & Key("SK").begins_with("REVIEW#")
        ),
        ScanIndexForward=False,  # descending SK order = newest first
    )
    reviews = resp.get("Items", [])
    if sort_by == "rating":
        reviews.sort(key=lambda r: int(r.get("rating", 0)), reverse=True)
    return reviews


def get_average_rating(reviews):
    """Average rating from an already-fetched review list."""
    if not reviews:
        return None
    total = sum(int(r["rating"]) for r in reviews)
    return round(total / len(reviews), 1)
