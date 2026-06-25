"""
create_table.py — Creates the ShopSphere table with its CategoryIndex GSI.

Run once before starting the app:
    python create_table.py

Works against real AWS or DynamoDB Local (set DYNAMODB_ENDPOINT_URL in .env).
"""

import os

import boto3
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "ShopSphere")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
ENDPOINT_URL = os.getenv("DYNAMODB_ENDPOINT_URL") or None

dynamodb = boto3.client("dynamodb", region_name=AWS_REGION, endpoint_url=ENDPOINT_URL)


def create_table():
    existing = dynamodb.list_tables()["TableNames"]
    if TABLE_NAME in existing:
        print(f"Table '{TABLE_NAME}' already exists — nothing to do.")
        return

    print(f"Creating table '{TABLE_NAME}' ...")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        # Only key attributes are declared — DynamoDB is schema-flexible
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},   # Partition Key
            {"AttributeName": "SK", "KeyType": "RANGE"},  # Sort Key
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "CategoryIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        # On-demand: pay per request, no capacity planning needed for an MVP
        BillingMode="PAY_PER_REQUEST",
    )

    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)
    print(f"Table '{TABLE_NAME}' is ready (with GSI 'CategoryIndex').")


if __name__ == "__main__":
    create_table()
