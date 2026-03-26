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
    categories = ['Pepsi Products', 'Coca-Cola Products', 'Beer', 'Packs', 'Cigarettes', 'Vapes']
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
        in_stock=request.form.get('in_stock') == 'on',
        image_url=request.form.get('image_url', '').strip() or None
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
    product.image_url = request.form.get('image_url', '').strip() or None
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

def seed_category(category, products):
    """Add products for a category only if that category doesn't exist yet."""
    if Product.query.filter_by(category=category).count() == 0:
        db.session.add_all(products)


def seed_data():
    """Seed initial products and admin account."""
    if Admin.query.count() == 0:
        admin = Admin(username='admin',
                      password_hash=generate_password_hash('yumyum2024'))
        db.session.add(admin)

    # Confirmed working image URL for Pepsi (verified via Open Food Facts)
    pepsi_img = 'https://images.openfoodfacts.org/images/products/001/200/080/9941/front_en.5.400.jpg'
    seed_category('Pepsi Products', [
        Product(name='Pepsi', category='Pepsi Products', size='12oz Can', price=1.75, image_url=pepsi_img),
        Product(name='Pepsi', category='Pepsi Products', size='20oz Bottle', price=2.49, image_url=pepsi_img),
        Product(name='Pepsi', category='Pepsi Products', size='8-Pack 12oz Cans', price=7.99, image_url=pepsi_img),
        Product(name='Pepsi', category='Pepsi Products', size='15-Pack 12oz Cans', price=12.99, image_url=pepsi_img),
        Product(name='Pepsi', category='Pepsi Products', size='20-Pack 12oz Cans', price=15.99, image_url=pepsi_img),
        Product(name='Diet Pepsi', category='Pepsi Products', size='12oz Can', price=1.75,
                image_url='https://placehold.co/200x200/003087/white?text=Diet+Pepsi'),
        Product(name='Mountain Dew', category='Pepsi Products', size='12oz Can', price=1.75,
                image_url='https://placehold.co/200x200/007a33/white?text=Mtn+Dew'),
        Product(name='Mountain Dew', category='Pepsi Products', size='20oz Bottle', price=2.49,
                image_url='https://placehold.co/200x200/007a33/white?text=Mtn+Dew+20oz'),
        Product(name='Gatorade', category='Pepsi Products', size='20oz Bottle', price=2.99,
                image_url='https://placehold.co/200x200/f47920/white?text=Gatorade'),
    ])

    # Confirmed working image URLs for Coca-Cola products (verified via Open Food Facts)
    seed_category('Coca-Cola Products', [
        Product(name='Coca-Cola', category='Coca-Cola Products', size='12oz Can', price=1.75,
                image_url='https://images.openfoodfacts.org/images/products/004/900/002/8904/front_en.16.400.jpg'),
        Product(name='Coca-Cola', category='Coca-Cola Products', size='20oz Bottle', price=2.49,
                image_url='https://images.openfoodfacts.org/images/products/004/900/000/0443/front_en.19.400.jpg'),
        Product(name='Coca-Cola', category='Coca-Cola Products', size='12-Pack 12oz Cans', price=9.99,
                image_url='https://images.openfoodfacts.org/images/products/004/900/002/8904/front_en.16.400.jpg'),
        Product(name='Coca-Cola', category='Coca-Cola Products', size='2L Bottle', price=2.99,
                image_url='https://images.openfoodfacts.org/images/products/004/900/000/0443/front_en.19.400.jpg'),
        Product(name='Coca-Cola Zero Sugar', category='Coca-Cola Products', size='20oz Bottle', price=2.49,
                image_url='https://images.openfoodfacts.org/images/products/004/900/004/0869/front_en.67.400.jpg'),
        Product(name='Coca-Cola Zero Sugar', category='Coca-Cola Products', size='24-Pack 12oz Cans', price=16.99,
                image_url='https://images.openfoodfacts.org/images/products/004/900/004/0869/front_en.67.400.jpg'),
        Product(name='Coca-Cola Zero Sugar', category='Coca-Cola Products', size='2L Bottle', price=2.99,
                image_url='https://images.openfoodfacts.org/images/products/004/900/004/0869/front_en.67.400.jpg'),
        Product(name='Diet Coke', category='Coca-Cola Products', size='12oz Can', price=1.75,
                image_url='https://images.openfoodfacts.org/images/products/004/900/002/8911/front_en.24.400.jpg'),
        Product(name='Diet Coke', category='Coca-Cola Products', size='12-Pack 12oz Cans', price=9.99,
                image_url='https://images.openfoodfacts.org/images/products/004/900/002/8911/front_en.24.400.jpg'),
        Product(name='Diet Coke Caffeine Free', category='Coca-Cola Products', size='12-Pack 12oz Cans', price=9.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Diet+Coke+Caff+Free'),
        Product(name='Diet Coke Cherry', category='Coca-Cola Products', size='12-Pack 12oz Cans', price=9.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Diet+Coke+Cherry'),
        Product(name='Diet Coke Lime', category='Coca-Cola Products', size='12-Pack 12oz Cans', price=9.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Diet+Coke+Lime'),
        Product(name='Sprite', category='Coca-Cola Products', size='12oz Can', price=1.75,
                image_url='https://placehold.co/200x200/00a651/white?text=Sprite'),
        Product(name='Sprite', category='Coca-Cola Products', size='20oz Bottle', price=2.49,
                image_url='https://placehold.co/200x200/00a651/white?text=Sprite+20oz'),
        Product(name='Dr Pepper', category='Coca-Cola Products', size='20oz Bottle', price=2.49,
                image_url='https://placehold.co/200x200/6b1a2b/white?text=Dr+Pepper'),
        Product(name='Dr Pepper', category='Coca-Cola Products', size='12oz Can', price=1.75,
                image_url='https://placehold.co/200x200/6b1a2b/white?text=Dr+Pepper'),
    ])

    seed_category('Beer', [
        Product(name='Budweiser', category='Beer', size='24oz Can', price=3.49,
                image_url='https://placehold.co/200x200/c8102e/white?text=Budweiser'),
        Product(name='Bud Light', category='Beer', size='24oz Can', price=3.49,
                image_url='https://placehold.co/200x200/0057a8/white?text=Bud+Light'),
        Product(name='Coors Light', category='Beer', size='24oz Can', price=3.49,
                image_url='https://placehold.co/200x200/7eb8d4/333333?text=Coors+Light'),
        Product(name='Miller Lite', category='Beer', size='24oz Can', price=3.49,
                image_url='https://placehold.co/200x200/1b3a6b/white?text=Miller+Lite'),
        Product(name='Miller High Life', category='Beer', size='24oz Can', price=2.99,
                image_url='https://placehold.co/200x200/f4c430/333333?text=Miller+High+Life'),
        Product(name='Miller Genuine Draft', category='Beer', size='24oz Can', price=3.29,
                image_url='https://placehold.co/200x200/2e7d32/white?text=Miller+Genuine+Draft'),
        Product(name='Corona', category='Beer', size='24oz Bottle', price=3.99,
                image_url='https://placehold.co/200x200/e8d44d/333333?text=Corona'),
        Product(name='Blue Moon', category='Beer', size='24oz Can', price=4.29,
                image_url='https://placehold.co/200x200/1a5276/white?text=Blue+Moon'),
        Product(name='Angry Orchard', category='Beer', size='24oz Can', price=4.29,
                image_url='https://placehold.co/200x200/8b0000/white?text=Angry+Orchard'),
        Product(name='Victoria', category='Beer', size='24oz Can', price=3.79,
                image_url='https://placehold.co/200x200/c62828/white?text=Victoria'),
        Product(name='Modelo Especial', category='Beer', size='24oz Can', price=3.99,
                image_url='https://placehold.co/200x200/8d6e14/white?text=Modelo+Especial'),
        Product(name='Heineken', category='Beer', size='24oz Bottle', price=4.29,
                image_url='https://placehold.co/200x200/00852a/white?text=Heineken'),
        Product(name='Rolling Rock', category='Beer', size='24oz Can', price=3.19,
                image_url='https://placehold.co/200x200/1b5e20/white?text=Rolling+Rock'),
        Product(name='Yuengling', category='Beer', size='24oz Can', price=3.49,
                image_url='https://placehold.co/200x200/b71c1c/white?text=Yuengling'),
    ])

    seed_category('Packs', [
        Product(name='Budweiser', category='Packs', size='6-Pack', price=10.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Budweiser+6pk'),
        Product(name='Budweiser', category='Packs', size='12-Pack', price=19.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Budweiser+12pk'),
        Product(name='Budweiser', category='Packs', size='24-Pack', price=29.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Budweiser+24pk'),
        Product(name='Bud Light', category='Packs', size='6-Pack', price=10.99,
                image_url='https://placehold.co/200x200/0057a8/white?text=Bud+Light+6pk'),
        Product(name='Bud Light', category='Packs', size='12-Pack', price=19.99,
                image_url='https://placehold.co/200x200/0057a8/white?text=Bud+Light+12pk'),
        Product(name='Bud Light', category='Packs', size='24-Pack', price=29.99,
                image_url='https://placehold.co/200x200/0057a8/white?text=Bud+Light+24pk'),
        Product(name='Coors Light', category='Packs', size='6-Pack', price=10.49,
                image_url='https://placehold.co/200x200/7eb8d4/333333?text=Coors+Light+6pk'),
        Product(name='Coors Light', category='Packs', size='12-Pack', price=18.99,
                image_url='https://placehold.co/200x200/7eb8d4/333333?text=Coors+Light+12pk'),
        Product(name='Coors Light', category='Packs', size='24-Pack', price=27.99,
                image_url='https://placehold.co/200x200/7eb8d4/333333?text=Coors+Light+24pk'),
        Product(name='Miller Lite', category='Packs', size='6-Pack', price=10.49,
                image_url='https://placehold.co/200x200/1b3a6b/white?text=Miller+Lite+6pk'),
        Product(name='Miller Lite', category='Packs', size='12-Pack', price=18.99,
                image_url='https://placehold.co/200x200/1b3a6b/white?text=Miller+Lite+12pk'),
        Product(name='Miller Lite', category='Packs', size='24-Pack', price=28.99,
                image_url='https://placehold.co/200x200/1b3a6b/white?text=Miller+Lite+24pk'),
        Product(name='Miller High Life', category='Packs', size='6-Pack', price=8.99,
                image_url='https://placehold.co/200x200/f4c430/333333?text=High+Life+6pk'),
        Product(name='Miller High Life', category='Packs', size='12-Pack', price=15.99,
                image_url='https://placehold.co/200x200/f4c430/333333?text=High+Life+12pk'),
        Product(name='Miller High Life', category='Packs', size='24-Pack', price=21.99,
                image_url='https://placehold.co/200x200/f4c430/333333?text=High+Life+24pk'),
        Product(name='Blue Moon', category='Packs', size='6-Pack', price=12.99,
                image_url='https://placehold.co/200x200/1a5276/white?text=Blue+Moon+6pk'),
        Product(name='Blue Moon', category='Packs', size='12-Pack', price=22.99,
                image_url='https://placehold.co/200x200/1a5276/white?text=Blue+Moon+12pk'),
        Product(name='Angry Orchard', category='Packs', size='6-Pack', price=11.99,
                image_url='https://placehold.co/200x200/8b0000/white?text=Angry+Orchard+6pk'),
        Product(name='Angry Orchard', category='Packs', size='12-Pack', price=19.99,
                image_url='https://placehold.co/200x200/8b0000/white?text=Angry+Orchard+12pk'),
        Product(name='Victoria', category='Packs', size='6-Pack', price=10.99,
                image_url='https://placehold.co/200x200/c62828/white?text=Victoria+6pk'),
        Product(name='Victoria', category='Packs', size='12-Pack', price=18.99,
                image_url='https://placehold.co/200x200/c62828/white?text=Victoria+12pk'),
        Product(name='Modelo Especial', category='Packs', size='6-Pack', price=12.99,
                image_url='https://placehold.co/200x200/8d6e14/white?text=Modelo+6pk'),
        Product(name='Modelo Especial', category='Packs', size='12-Pack', price=23.99,
                image_url='https://placehold.co/200x200/8d6e14/white?text=Modelo+12pk'),
        Product(name='Modelo Especial', category='Packs', size='24-Pack', price=37.99,
                image_url='https://placehold.co/200x200/8d6e14/white?text=Modelo+24pk'),
        Product(name='Heineken', category='Packs', size='6-Pack', price=13.49,
                image_url='https://placehold.co/200x200/00852a/white?text=Heineken+6pk'),
        Product(name='Heineken', category='Packs', size='12-Pack', price=23.99,
                image_url='https://placehold.co/200x200/00852a/white?text=Heineken+12pk'),
        Product(name='Corona', category='Packs', size='6-Pack', price=11.99,
                image_url='https://placehold.co/200x200/e8d44d/333333?text=Corona+6pk'),
        Product(name='Corona', category='Packs', size='12-Pack', price=20.99,
                image_url='https://placehold.co/200x200/e8d44d/333333?text=Corona+12pk'),
        Product(name='Yuengling', category='Packs', size='6-Pack', price=10.49,
                image_url='https://placehold.co/200x200/b71c1c/white?text=Yuengling+6pk'),
        Product(name='Yuengling', category='Packs', size='12-Pack', price=17.99,
                image_url='https://placehold.co/200x200/b71c1c/white?text=Yuengling+12pk'),
        Product(name='Rolling Rock', category='Packs', size='6-Pack', price=9.49,
                image_url='https://placehold.co/200x200/1b5e20/white?text=Rolling+Rock+6pk'),
        Product(name='Rolling Rock', category='Packs', size='12-Pack', price=15.99,
                image_url='https://placehold.co/200x200/1b5e20/white?text=Rolling+Rock+12pk'),
    ])

    seed_category('Cigarettes', [
        # Camel
        Product(name='Camel Blue', category='Cigarettes', size='King Box', price=10.99,
                image_url='https://placehold.co/200x200/8B6914/white?text=Camel+Blue'),
        Product(name='Camel Turkish Silver', category='Cigarettes', size='King Box', price=10.99,
                image_url='https://placehold.co/200x200/8B6914/white?text=Camel+Silver'),
        Product(name='Camel Turkish Gold', category='Cigarettes', size='King Box', price=10.99,
                image_url='https://placehold.co/200x200/8B6914/white?text=Camel+Gold'),
        Product(name='Camel Menthol', category='Cigarettes', size='King Box', price=10.99,
                image_url='https://placehold.co/200x200/8B6914/white?text=Camel+Menthol'),
        Product(name='Camel Crush Menthol', category='Cigarettes', size='King Box', price=10.99,
                image_url='https://placehold.co/200x200/8B6914/white?text=Camel+Crush'),
        Product(name='Camel 99s', category='Cigarettes', size='100s Box', price=11.49,
                image_url='https://placehold.co/200x200/8B6914/white?text=Camel+99s'),
        # Newport
        Product(name='Newport', category='Cigarettes', size='King Box', price=12.49,
                image_url='https://placehold.co/200x200/006400/white?text=Newport'),
        Product(name='Newport 100s', category='Cigarettes', size='100s Box', price=12.99,
                image_url='https://placehold.co/200x200/006400/white?text=Newport+100s'),
        Product(name='Newport Non-Menthol', category='Cigarettes', size='King Box', price=12.49,
                image_url='https://placehold.co/200x200/006400/white?text=Newport+Non-Menth'),
        # Marlboro
        Product(name='Marlboro Red', category='Cigarettes', size='King Box', price=11.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Marlboro+Red'),
        Product(name='Marlboro Gold', category='Cigarettes', size='King Box', price=11.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Marlboro+Gold'),
        Product(name='Marlboro Silver', category='Cigarettes', size='King Box', price=11.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Marlboro+Silver'),
        Product(name='Marlboro Menthol', category='Cigarettes', size='King Box', price=11.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Marlboro+Menthol'),
        Product(name='Marlboro Black', category='Cigarettes', size='King Box', price=11.99,
                image_url='https://placehold.co/200x200/c8102e/white?text=Marlboro+Black'),
        Product(name='Marlboro 100s', category='Cigarettes', size='100s Box', price=12.49,
                image_url='https://placehold.co/200x200/c8102e/white?text=Marlboro+100s'),
        # Budget / Value Brands
        Product(name='24/7 Regular', category='Cigarettes', size='King Box', price=7.49,
                image_url='https://placehold.co/200x200/555555/white?text=24-7+Regular'),
        Product(name='24/7 Menthol', category='Cigarettes', size='King Box', price=7.49,
                image_url='https://placehold.co/200x200/555555/white?text=24-7+Menthol'),
        Product(name='24/7 Lights', category='Cigarettes', size='King Box', price=7.49,
                image_url='https://placehold.co/200x200/555555/white?text=24-7+Lights'),
        Product(name='305s Regular', category='Cigarettes', size='King Box', price=6.49,
                image_url='https://placehold.co/200x200/444444/white?text=305s+Regular'),
        Product(name='305s Menthol', category='Cigarettes', size='King Box', price=6.49,
                image_url='https://placehold.co/200x200/444444/white?text=305s+Menthol'),
        Product(name='305s Lights', category='Cigarettes', size='King Box', price=6.49,
                image_url='https://placehold.co/200x200/444444/white?text=305s+Lights'),
        Product(name='Pall Mall Red', category='Cigarettes', size='King Box', price=8.49,
                image_url='https://placehold.co/200x200/990000/white?text=Pall+Mall+Red'),
        Product(name='Pall Mall Blue', category='Cigarettes', size='King Box', price=8.49,
                image_url='https://placehold.co/200x200/990000/white?text=Pall+Mall+Blue'),
        Product(name='Pall Mall Menthol', category='Cigarettes', size='King Box', price=8.49,
                image_url='https://placehold.co/200x200/990000/white?text=Pall+Mall+Menth'),
        Product(name='Pyramid Regular', category='Cigarettes', size='King Box', price=7.49,
                image_url='https://placehold.co/200x200/6d4c41/white?text=Pyramid+Regular'),
        Product(name='Pyramid Menthol', category='Cigarettes', size='King Box', price=7.49,
                image_url='https://placehold.co/200x200/6d4c41/white?text=Pyramid+Menthol'),
        # Other Brands
        Product(name='Winston Red', category='Cigarettes', size='King Box', price=9.99,
                image_url='https://placehold.co/200x200/b71c1c/white?text=Winston+Red'),
        Product(name='Winston Blue', category='Cigarettes', size='King Box', price=9.99,
                image_url='https://placehold.co/200x200/b71c1c/white?text=Winston+Blue'),
        Product(name='Kool Menthol', category='Cigarettes', size='King Box', price=10.99,
                image_url='https://placehold.co/200x200/004d40/white?text=Kool+Menthol'),
        Product(name='Salem Menthol', category='Cigarettes', size='King Box', price=10.49,
                image_url='https://placehold.co/200x200/1b5e20/white?text=Salem+Menthol'),
        Product(name='L&M Red', category='Cigarettes', size='King Box', price=8.99,
                image_url='https://placehold.co/200x200/c62828/white?text=L%26M+Red'),
        Product(name='L&M Blue', category='Cigarettes', size='King Box', price=8.99,
                image_url='https://placehold.co/200x200/c62828/white?text=L%26M+Blue'),
        Product(name='American Spirit Yellow', category='Cigarettes', size='King Box', price=14.99,
                image_url='https://placehold.co/200x200/f9a825/333333?text=Am+Spirit+Yellow'),
        Product(name='American Spirit Blue', category='Cigarettes', size='King Box', price=14.99,
                image_url='https://placehold.co/200x200/f9a825/333333?text=Am+Spirit+Blue'),
        Product(name='American Spirit Organic', category='Cigarettes', size='King Box', price=15.99,
                image_url='https://placehold.co/200x200/f9a825/333333?text=Am+Spirit+Organic'),
    ])

    seed_category('Vapes', [
        # Breeze
        Product(name='Breeze Pro', category='Vapes', size='2000 Puffs', price=15.99,
                image_url='https://placehold.co/200x200/6a1b9a/white?text=Breeze+Pro'),
        Product(name='Breeze Plus', category='Vapes', size='800 Puffs', price=10.99,
                image_url='https://placehold.co/200x200/6a1b9a/white?text=Breeze+Plus'),
        Product(name='Breeze Prime', category='Vapes', size='6000 Puffs', price=21.99,
                image_url='https://placehold.co/200x200/6a1b9a/white?text=Breeze+Prime'),
        # Elf Bar
        Product(name='Elf Bar BC5000', category='Vapes', size='5000 Puffs', price=17.99,
                image_url='https://placehold.co/200x200/4a148c/white?text=Elf+Bar+5000'),
        Product(name='Elf Bar 600', category='Vapes', size='600 Puffs', price=9.99,
                image_url='https://placehold.co/200x200/4a148c/white?text=Elf+Bar+600'),
        # Lost Mary
        Product(name='Lost Mary OS5000', category='Vapes', size='5000 Puffs', price=17.99,
                image_url='https://placehold.co/200x200/880e4f/white?text=Lost+Mary+5000'),
        Product(name='Lost Mary BM600', category='Vapes', size='600 Puffs', price=9.99,
                image_url='https://placehold.co/200x200/880e4f/white?text=Lost+Mary+600'),
        # Hyde
        Product(name='Hyde Edge', category='Vapes', size='3300 Puffs', price=15.99,
                image_url='https://placehold.co/200x200/1a237e/white?text=Hyde+Edge'),
        Product(name='Hyde Rebel Pro', category='Vapes', size='5000 Puffs', price=18.99,
                image_url='https://placehold.co/200x200/1a237e/white?text=Hyde+Rebel+Pro'),
        # Vuse
        Product(name='Vuse Alto', category='Vapes', size='Device + Pod', price=13.99,
                image_url='https://placehold.co/200x200/212121/white?text=Vuse+Alto'),
        Product(name='Vuse Alto Pod', category='Vapes', size='2-Pack', price=11.99,
                image_url='https://placehold.co/200x200/212121/white?text=Vuse+Pod+2pk'),
        # Funky Republic
        Product(name='Funky Republic Ti7000', category='Vapes', size='7000 Puffs', price=19.99,
                image_url='https://placehold.co/200x200/e65100/white?text=Funky+Republic'),
        # Puff Bar
        Product(name='Puff Bar', category='Vapes', size='300 Puffs', price=8.99,
                image_url='https://placehold.co/200x200/bf360c/white?text=Puff+Bar'),
        Product(name='Puff Bar Plus', category='Vapes', size='800 Puffs', price=11.99,
                image_url='https://placehold.co/200x200/bf360c/white?text=Puff+Bar+Plus'),
        # Blu
        Product(name='Blu Disposable', category='Vapes', size='400 Puffs', price=9.99,
                image_url='https://placehold.co/200x200/0d47a1/white?text=Blu+Vape'),
    ])

    db.session.commit()


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == '__main__':
    app.run(debug=True)
