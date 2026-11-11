
-- =====================================================
-- DATASENSE - CREATION DU SCHEMA RELATIONNEL
-- PostgreSQL 18
-- =====================================================

-- 1. CUSTOMERS
CREATE TABLE customers (
    customer_id VARCHAR(50) PRIMARY KEY,
    customer_unique_id VARCHAR(50),
    customer_zip_code_prefix VARCHAR(10),
    customer_city VARCHAR(100),
    customer_state VARCHAR(10)
);

-- 2. ORDERS
CREATE TABLE orders (
    order_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    order_status VARCHAR(30),
    order_purchase_timestamp TIMESTAMP,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP,

    CONSTRAINT fk_orders_customers
        FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id)
);

-- 3. ORDER ITEMS
CREATE TABLE order_items (
    order_id VARCHAR(50) NOT NULL,
    order_item_id INTEGER NOT NULL,
    product_id VARCHAR(50),
    seller_id VARCHAR(50),
    shipping_limit_date TIMESTAMP,
    price NUMERIC(12, 2),
    freight_value NUMERIC(12, 2),

    PRIMARY KEY (order_id, order_item_id),

    CONSTRAINT fk_items_orders
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id)
);

-- 4. ORDER PAYMENTS
CREATE TABLE order_payments (
    order_id VARCHAR(50) NOT NULL,
    payment_sequential INTEGER NOT NULL,
    payment_type VARCHAR(50),
    payment_installments INTEGER,
    payment_value NUMERIC(12, 2),

    PRIMARY KEY (order_id, payment_sequential),

    CONSTRAINT fk_payments_orders
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id)
);

-- 5. ORDER REVIEWS
CREATE TABLE order_reviews (
    review_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50) NOT NULL,
    review_score SMALLINT,
    review_comment_title TEXT,
    review_comment_message TEXT,
    review_creation_date TIMESTAMP,
    review_answer_timestamp TIMESTAMP,

    PRIMARY KEY (review_id, order_id),

    CONSTRAINT fk_reviews_orders
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    CONSTRAINT chk_review_score
        CHECK (review_score BETWEEN 1 AND 5)
);

-- 6. INDEXES FOR COMMON JOINS
CREATE INDEX idx_orders_customer
    ON orders(customer_id);

CREATE INDEX idx_items_order
    ON order_items(order_id);

CREATE INDEX idx_payments_order
    ON order_payments(order_id);

CREATE INDEX idx_reviews_order
    ON order_reviews(order_id);

CREATE INDEX idx_customers_unique_id
    ON customers(customer_unique_id);
