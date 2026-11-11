--Nombre de commandes par statut
SELECT
    order_status,
    COUNT(*) AS nombre_commandes
FROM orders
GROUP BY order_status
ORDER BY nombre_commandes DESC;


--Chiffre d'affaires par mois
SELECT
    DATE_TRUNC('month', o.order_purchase_timestamp) AS mois,
    ROUND(SUM(oi.price), 2) AS chiffre_affaires
FROM orders o
JOIN order_items oi
    ON o.order_id = oi.order_id
WHERE o.order_status = 'delivered'
GROUP BY DATE_TRUNC('month', o.order_purchase_timestamp)
ORDER BY mois;


--Note moyenne des avis
SELECT
    ROUND(AVG(review_score), 2) AS note_moyenne,
    COUNT(*) AS nombre_avis
FROM order_reviews;



--Répartition des avis par note
SELECT
    review_score,
    COUNT(*) AS nombre_avis,
    ROUND(
        COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (),
        2
    ) AS pourcentage
FROM order_reviews
GROUP BY review_score
ORDER BY review_score;


--Délais moyens de livraison
SELECT
    ROUND(
        AVG(
            EXTRACT(
                EPOCH FROM (
                    order_delivered_customer_date
                    - order_purchase_timestamp
                )
            ) / 86400
        ),
        2
    ) AS delai_moyen_jours
FROM orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL;



--Les 10 avis les plus négatifs avec commentaire
SELECT
    r.review_score,
    r.review_comment_message,
    o.order_status,
    o.order_purchase_timestamp
FROM order_reviews r
JOIN orders o
    ON r.order_id = o.order_id
WHERE r.review_score <= 2
  AND r.review_comment_message IS NOT NULL
  AND TRIM(r.review_comment_message) <> ''
ORDER BY r.review_score ASC, r.review_creation_date DESC
LIMIT 10;