import json
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Product, Order, Admin

app = Flask(__name__)
app.secret_key = 'yumyum-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///yumyum.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Custom Jinja filter to parse JSON strings in templates
app.jinja_env.filters['from_json'] = json.loads


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_cart():
    return session.get('cart', [])


def save_cart(cart):
    session['cart'] = cart


def cart_total(cart):
    return round(sum(item['price'] * item['qty'] for item in cart), 2)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ── Customer Routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    featured = Product.query.filter_by(in_stock=True).limit(8).all()
    return render_template('index.html', featured=featured)


@app.route('/menu')
def menu():
    categories = ['Pepsi Products', 'Coca-Cola Products', 'Beer', 'Packs']
    products_by_cat = {}
    for cat in categories:
        products_by_cat[cat] = Product.query.filter_by(category=cat, in_stock=True).all()
    return render_template('menu.html', products_by_cat=products_by_cat)


@app.route('/cart')
def cart():
    cart = get_cart()
    return render_template('cart.html', cart=cart, total=cart_total(cart))


@app.route('/cart/add', methods=['POST'])
def cart_add():
    product_id = int(request.form.get('product_id'))
    qty = int(request.form.get('qty', 1))
    product = Product.query.get_or_404(product_id)

    cart = get_cart()
    for item in cart:
        if item['id'] == product_id:
            item['qty'] += qty
            break
    else:
        cart.append({'id': product_id, 'name': product.name, 'size': product.size,
                     'price': product.price, 'qty': qty})
    save_cart(cart)
    flash(f'{product.name} added to cart!', 'success')
    return redirect(request.referrer or url_for('menu'))


@app.route('/cart/remove/<int:product_id>')
def cart_remove(product_id):
    cart = [item for item in get_cart() if item['id'] != product_id]
    save_cart(cart)
    return redirect(url_for('cart'))


@app.route('/order', methods=['GET', 'POST'])
def order():
    cart = get_cart()
    if not cart:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('menu'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        pickup_time = request.form.get('pickup_time', '').strip()

        if not name or not phone:
            flash('Please fill in your name and phone number.', 'danger')
            return render_template('order.html', cart=cart, total=cart_total(cart))

        new_order = Order(
            customer_name=name,
            phone=phone,
            items=json.dumps(cart),
            total=cart_total(cart),
            pickup_time=pickup_time,
            status='pending'
        )
        db.session.add(new_order)
        db.session.commit()
        save_cart([])
        return redirect(url_for('order_confirm', order_id=new_order.id))

    return render_template('order.html', cart=cart, total=cart_total(cart))


@app.route('/order/confirm/<int:order_id>')
def order_confirm(order_id):
    order = Order.query.get_or_404(order_id)
    items = json.loads(order.items)
    return render_template('order_confirm.html', order=order, items=items)


# ── Admin Routes ──────────────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_logged_in'] = True
            session['admin_username'] = admin.username
            return redirect(url_for('admin_dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    total_products = Product.query.count()
    revenue = db.session.query(db.func.sum(Order.total)).scalar() or 0
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html',
                           total_orders=total_orders,
                           pending_orders=pending_orders,
                           total_products=total_products,
                           revenue=round(revenue, 2),
                           recent_orders=recent_orders)


@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.query.order_by(Product.category, Product.name).all()
    return render_template('admin/products.html', products=products)


@app.route('/admin/products/add', methods=['POST'])
@admin_required
def admin_products_add():
    product = Product(
        name=request.form.get('name'),
        category=request.form.get('category'),
        size=request.form.get('size'),
        price=float(request.form.get('price', 0)),
        in_stock=request.form.get('in_stock') == 'on'
    )
    db.session.add(product)
    db.session.commit()
    flash('Product added successfully.', 'success')
    return redirect(url_for('admin_products'))


@app.route('/admin/products/edit/<int:product_id>', methods=['POST'])
@admin_required
def admin_products_edit(product_id):
    product = Product.query.get_or_404(product_id)
    product.name = request.form.get('name')
    product.category = request.form.get('category')
    product.size = request.form.get('size')
    product.price = float(request.form.get('price', 0))
    product.in_stock = request.form.get('in_stock') == 'on'
    db.session.commit()
    flash('Product updated.', 'success')
    return redirect(url_for('admin_products'))


@app.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@admin_required
def admin_products_delete(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'success')
    return redirect(url_for('admin_products'))


@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders)


@app.route('/admin/orders/status/<int:order_id>', methods=['POST'])
@admin_required
def admin_orders_status(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = request.form.get('status')
    db.session.commit()
    flash('Order status updated.', 'success')
    return redirect(url_for('admin_orders'))


# ── Startup ───────────────────────────────────────────────────────────────────

def seed_data():
    """Seed initial products and admin account."""
    if Admin.query.count() == 0:
        admin = Admin(username='admin',
                      password_hash=generate_password_hash('yumyum2024'))
        db.session.add(admin)

    if Product.query.count() == 0:
        products = [
            # Pepsi Products
            Product(name='Pepsi', category='Pepsi Products', size='12oz Can', price=1.50),
            Product(name='Pepsi', category='Pepsi Products', size='20oz Bottle', price=2.25),
            Product(name='Diet Pepsi', category='Pepsi Products', size='12oz Can', price=1.50),
            Product(name='Mountain Dew', category='Pepsi Products', size='12oz Can', price=1.50),
            Product(name='Mountain Dew', category='Pepsi Products', size='20oz Bottle', price=2.25),
            Product(name='Gatorade', category='Pepsi Products', size='20oz Bottle', price=2.50),
            # Coca-Cola Products
            Product(name='Coca-Cola', category='Coca-Cola Products', size='12oz Can', price=1.50),
            Product(name='Coca-Cola', category='Coca-Cola Products', size='20oz Bottle', price=2.25),
            Product(name='Diet Coke', category='Coca-Cola Products', size='12oz Can', price=1.50),
            Product(name='Sprite', category='Coca-Cola Products', size='12oz Can', price=1.50),
            Product(name='Dr Pepper', category='Coca-Cola Products', size='20oz Bottle', price=2.25),
            # Beer
            Product(name='Budweiser', category='Beer', size='12oz Can', price=2.00),
            Product(name='Bud Light', category='Beer', size='12oz Can', price=2.00),
            Product(name='Coors Light', category='Beer', size='12oz Can', price=2.00),
            Product(name='Miller Lite', category='Beer', size='12oz Can', price=2.00),
            Product(name='Corona', category='Beer', size='12oz Bottle', price=2.50),
            # Packs
            Product(name='Budweiser', category='Packs', size='6-Pack', price=9.99),
            Product(name='Budweiser', category='Packs', size='12-Pack', price=17.99),
            Product(name='Budweiser', category='Packs', size='24-Pack', price=29.99),
            Product(name='Bud Light', category='Packs', size='6-Pack', price=9.99),
            Product(name='Bud Light', category='Packs', size='12-Pack', price=17.99),
            Product(name='Bud Light', category='Packs', size='24-Pack', price=29.99),
            Product(name='Coors Light', category='Packs', size='6-Pack', price=9.99),
            Product(name='Coors Light', category='Packs', size='12-Pack', price=17.99),
            Product(name='Miller Lite', category='Packs', size='24-Pack', price=29.99),
        ]
        db.session.add_all(products)

    db.session.commit()


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == '__main__':
    app.run(debug=True)
