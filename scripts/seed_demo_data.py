"""
DataSense - Demo Data Seeder for Testing & Baseline Evaluation.
Populates realistic sample e-commerce records (customers, orders, items, payments, reviews)
when the database tables are empty, enabling genuine query execution and metric validation.
"""

import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import random

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.db import get_engine
from sqlalchemy import text

def seed_database(force: bool = False):
    engine = get_engine()
    
    with engine.connect() as conn:
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders;")).scalar()
        if order_count > 0 and not force:
            print(f"Database already contains {order_count} orders. Seeding skipped.")
            return

    print("Seeding database with realistic Olist e-commerce sample records...")
    
    random.seed(42)
    
    states = ["SP", "RJ", "MG", "RS", "PR", "BA", "SC", "PE", "CE", "DF"]
    cities = {
        "SP": "sao paulo", "RJ": "rio de janeiro", "MG": "belo horizonte",
        "RS": "porto alegre", "PR": "curitiba", "BA": "salvador",
        "SC": "florianopolis", "PE": "recife", "CE": "fortaleza", "DF": "brasilia"
    }
    
    categories = [
        "beleza_saude", "informatica_acessorios", "cama_mesa_banho",
        "esporte_lazer", "relogios_presentes", "utilidades_domesticas",
        "telefonia", "ferramentas_jardim", "automotivo", "brinquedos"
    ]
    
    # 1. Generate 60 customers
    customers = []
    for i in range(1, 61):
        st = random.choice(states)
        customers.append({
            "customer_id": f"c_{i:04d}",
            "customer_unique_id": f"cu_{i:04d}",
            "customer_zip_code_prefix": f"{random.randint(10000, 99999)}",
            "customer_city": cities[st],
            "customer_state": st
        })
    df_customers = pd.DataFrame(customers)
    
    # 2. Generate 100 orders across 2016, 2017, and 2018
    statuses = ["delivered"] * 85 + ["shipped"] * 8 + ["canceled"] * 4 + ["invoiced"] * 3
    orders = []
    items = []
    payments = []
    reviews = []
    
    base_dates = [
        datetime(2017, 1, 15), datetime(2017, 6, 20), datetime(2017, 11, 25),
        datetime(2018, 2, 10), datetime(2018, 4, 18), datetime(2018, 7, 22),
        datetime(2018, 8, 14), datetime(2018, 10, 5)
    ]
    
    for i in range(1, 101):
        order_id = f"o_{i:04d}"
        cust = random.choice(customers)
        status = statuses[i - 1]
        
        # Pick purchase date (some in 2017, some in 2018)
        year = 2018 if i > 35 else 2017
        month = random.randint(1, 12) if year == 2017 else random.randint(1, 10)
        day = random.randint(1, 28)
        purchase_date = datetime(year, month, day, random.randint(8, 21), random.randint(0, 59))
        approved_at = purchase_date + timedelta(hours=random.randint(1, 12))
        carrier_date = approved_at + timedelta(days=random.randint(1, 3))
        
        delivered_date = None
        if status == "delivered":
            delivered_date = carrier_date + timedelta(days=random.randint(3, 14))
            
        estimated_delivery = purchase_date + timedelta(days=random.randint(15, 25))
        
        orders.append({
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "order_status": status,
            "order_purchase_timestamp": purchase_date,
            "order_approved_at": approved_at,
            "order_delivered_carrier_date": carrier_date if status in ["delivered", "shipped"] else None,
            "order_delivered_customer_date": delivered_date,
            "order_estimated_delivery_date": estimated_delivery
        })
        
        # 3. Order Items (1 to 3 items per order)
        num_items = random.choices([1, 2, 3], weights=[0.75, 0.20, 0.05])[0]
        total_order_val = 0.0
        for item_idx in range(1, num_items + 1):
            price = round(random.uniform(15.0, 350.0), 2)
            freight = round(random.uniform(8.0, 45.0), 2)
            total_order_val += price + freight
            seller_id = f"s_{random.randint(1, 15):03d}"
            product_id = f"p_{random.randint(1, 30):03d}"
            items.append({
                "order_id": order_id,
                "order_item_id": item_idx,
                "product_id": product_id,
                "seller_id": seller_id,
                "shipping_limit_date": approved_at + timedelta(days=5),
                "price": price,
                "freight_value": freight
            })
            
        # 4. Order Payments
        payments.append({
            "order_id": order_id,
            "payment_sequential": 1,
            "payment_type": random.choice(["credit_card", "credit_card", "boleto", "voucher", "debit_card"]),
            "payment_installments": random.choice([1, 1, 2, 3, 6, 10]),
            "payment_value": round(total_order_val, 2)
        })
        
        # 5. Order Reviews (for 90% of orders)
        if random.random() < 0.90:
            score = random.choices([5, 4, 3, 2, 1], weights=[0.55, 0.20, 0.10, 0.05, 0.10])[0]
            review_creation = (delivered_date or purchase_date) + timedelta(days=1)
            msg = None
            if score >= 4:
                msg = random.choice([
                    "Excelente produto, chegou muito rápido!",
                    "Muito satisfeito com a compra, recomendo a todos.",
                    "Perfeito estado e entrega antes do prazo.",
                    "Otimo atendimento e qualidade impecavel."
                ])
            elif score == 3:
                msg = "O produto é razoável, porém a entrega demorou."
            else:
                msg = random.choice([
                    "Produto veio com defeito e atrasou duas semanas.",
                    "Péssimo serviço, embalagem toda rasgada.",
                    "Não recebi o item correto, aguardo solução."
                ])
                
            reviews.append({
                "review_id": f"rev_{i:04d}",
                "order_id": order_id,
                "review_score": score,
                "review_comment_title": "Avaliação",
                "review_comment_message": msg,
                "review_creation_date": review_creation,
                "review_answer_timestamp": review_creation + timedelta(days=1)
            })

    df_orders = pd.DataFrame(orders)
    df_items = pd.DataFrame(items)
    df_payments = pd.DataFrame(payments)
    df_reviews = pd.DataFrame(reviews)
    
    with engine.begin() as conn:
        df_customers.to_sql("customers", conn, if_exists="append", index=False)
        df_orders.to_sql("orders", conn, if_exists="append", index=False)
        df_items.to_sql("order_items", conn, if_exists="append", index=False)
        df_payments.to_sql("order_payments", conn, if_exists="append", index=False)
        df_reviews.to_sql("order_reviews", conn, if_exists="append", index=False)
        
    print(f"Successfully seeded:")
    print(f"  - {len(df_customers)} customers")
    print(f"  - {len(df_orders)} orders ({len(df_orders[df_orders['order_status']=='delivered'])} delivered)")
    print(f"  - {len(df_items)} order items")
    print(f"  - {len(df_payments)} payments")
    print(f"  - {len(df_reviews)} reviews (average score: {df_reviews['review_score'].mean():.2f})")

if __name__ == "__main__":
    seed_database()
