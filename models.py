from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # Pepsi, Coca-Cola, Beer, Packs
    size = db.Column(db.String(50))                       # 12oz Can, 20oz Bottle, 6-Pack, etc.
    price = db.Column(db.Float, nullable=False)
    in_stock = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String(500), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'size': self.size,
            'price': self.price,
            'in_stock': self.in_stock,
            'image_url': self.image_url,
        }


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    items = db.Column(db.Text, nullable=False)   # JSON string
    total = db.Column(db.Float, nullable=False)
    pickup_time = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')  # pending / ready / completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
