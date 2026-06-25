"""
seed_data.py — Optional: loads a few demo products and reviews
so the catalog isn't empty when you record your video.

    python seed_data.py
"""

import db

PRODUCTS = [
    dict(name="Wireless Mouse", description="Ergonomic 2.4 GHz wireless mouse with silent clicks.",
         category="Electronics", price=14.99, stock=120,
         image_url="https://placehold.co/300x200?text=Mouse"),
    dict(name="Mechanical Keyboard", description="RGB mechanical keyboard, blue switches.",
         category="Electronics", price=49.50, stock=45,
         image_url="https://placehold.co/300x200?text=Keyboard"),
    dict(name="Stainless Water Bottle", description="750 ml insulated bottle, keeps drinks cold 24 h.",
         category="Home", price=11.00, stock=200,
         image_url="https://placehold.co/300x200?text=Bottle"),
    dict(name="Yoga Mat", description="Non-slip 6 mm yoga mat with carry strap.",
         category="Sports", price=18.75, stock=80,
         image_url="https://placehold.co/300x200?text=Yoga+Mat"),
]

REVIEWS = [
    ("Ahmad", 5, "Excellent quality, fast delivery!"),
    ("Sara", 4, "Very good but the box arrived slightly damaged."),
    ("Omar", 3, "Does the job, nothing special."),
]


def main():
    for p in PRODUCTS:
        pid = db.create_product(**p)
        print(f"Created product {p['name']} -> {pid}")
        for customer, rating, comment in REVIEWS:
            db.add_review(pid, customer, rating, comment)
    print("Seeding complete.")


if __name__ == "__main__":
    main()
