"""
app.py — Flask routes for ShopSphere.
All DynamoDB logic lives in db.py; routes stay thin.
"""

import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for

import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


# ---------------------------------------------------------------------------
# Helpers / validation
# ---------------------------------------------------------------------------

def _validate_product_form(form):
    """Return (clean_data, errors) for the product add/edit forms."""
    errors = []
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "").strip()
    price = form.get("price", "").strip()
    stock = form.get("stock", "").strip()
    image_url = form.get("image_url", "").strip()

    if not name:
        errors.append("Product name is required.")
    if not category:
        errors.append("Category is required.")
    try:
        price_val = float(price)
        if price_val < 0:
            errors.append("Price cannot be negative.")
    except ValueError:
        errors.append("Price must be a valid number.")
        price_val = 0
    try:
        stock_val = int(stock)
        if stock_val < 0:
            errors.append("Stock cannot be negative.")
    except ValueError:
        errors.append("Stock must be a whole number.")
        stock_val = 0

    data = {
        "name": name,
        "description": description,
        "category": category,
        "price": price_val,
        "stock": stock_val,
        "image_url": image_url,
    }
    return data, errors


# ---------------------------------------------------------------------------
# Product catalog
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Product listing — optionally filtered by category via the GSI."""
    category = request.args.get("category", "").strip()
    if category:
        products = db.list_products_by_category(category)  # GSI Query
    else:
        products = db.list_products()  # Scan (full catalog view)

    categories = db.get_all_categories()
    return render_template(
        "index.html",
        products=products,
        categories=categories,
        selected_category=category,
    )


@app.route("/product/add", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        data, errors = _validate_product_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("product_form.html", product=data, mode="add")
        product_id = db.create_product(**data)
        flash("Product created successfully.", "success")
        return redirect(url_for("product_detail", product_id=product_id))
    return render_template("product_form.html", product=None, mode="add")


@app.route("/product/<product_id>")
def product_detail(product_id):
    product = db.get_product(product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("index"))

    sort_by = request.args.get("sort", "date")  # 'date' or 'rating'
    reviews = db.get_reviews(product_id, sort_by=sort_by)
    avg_rating = db.get_average_rating(reviews)

    return render_template(
        "product_detail.html",
        product=product,
        reviews=reviews,
        avg_rating=avg_rating,
        sort_by=sort_by,
    )


@app.route("/product/<product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    product = db.get_product(product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        data, errors = _validate_product_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            data["product_id"] = product_id
            return render_template("product_form.html", product=data, mode="edit")
        db.update_product(product_id, **data)
        flash("Product updated.", "success")
        return redirect(url_for("product_detail", product_id=product_id))

    return render_template("product_form.html", product=product, mode="edit")


@app.route("/product/<product_id>/delete", methods=["POST"])
def delete_product(product_id):
    """Admin-only delete (simulated — no auth layer in the MVP)."""
    if not db.get_product(product_id):
        flash("Product not found.", "error")
        return redirect(url_for("index"))
    db.delete_product(product_id)
    flash("Product deleted (including its reviews).", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Customer feedback
# ---------------------------------------------------------------------------

@app.route("/product/<product_id>/review", methods=["POST"])
def add_review(product_id):
    if not db.get_product(product_id):
        flash("Product not found.", "error")
        return redirect(url_for("index"))

    customer_name = request.form.get("customer_name", "").strip()
    rating = request.form.get("rating", "").strip()
    comment = request.form.get("comment", "").strip()

    errors = []
    if not customer_name:
        errors.append("Your name is required.")
    try:
        rating_val = int(rating)
        if not 1 <= rating_val <= 5:
            errors.append("Rating must be between 1 and 5.")
    except ValueError:
        errors.append("Rating must be a number from 1 to 5.")
        rating_val = 0
    if not comment:
        errors.append("A comment is required.")

    if errors:
        for e in errors:
            flash(e, "error")
    else:
        db.add_review(product_id, customer_name, rating_val, comment)
        flash("Thank you! Your review was submitted.", "success")

    return redirect(url_for("product_detail", product_id=product_id))


if __name__ == "__main__":
    app.run(debug=True)
