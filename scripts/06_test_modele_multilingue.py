from sentence_transformers import SentenceTransformer, util

print("=" * 65)
print("DATASENSE - TEST DU MODELE MULTILINGUE")
print("=" * 65)

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

print("\nChargement du modèle...")
model = SentenceTransformer(MODEL_NAME)

print("Modèle chargé avec succès.")

# Trois phrases pour tester la correspondance français-portugais
phrases = [
    "Mon colis est arrivé très en retard.",
    "Meu pedido chegou muito atrasado.",
    "Le produit est de très bonne qualité."
]

print("\nGénération des embeddings...")
embeddings = model.encode(
    phrases,
    convert_to_tensor=True,
    normalize_embeddings=True
)

print("Embeddings générés.")

print("\nDimensions des vecteurs :")
print(embeddings.shape)

# Comparaison des deux premières phrases
similarity_1 = util.cos_sim(
    embeddings[0],
    embeddings[1]
).item()

# Comparaison entre une phrase française et une phrase sans rapport
similarity_2 = util.cos_sim(
    embeddings[0],
    embeddings[2]
).item()

print("\nRésultats de similarité :")
print(
    "Français / Portugais (retard de livraison) :",
    round(similarity_1, 4)
)
print(
    "Français / Français (sujet différent) :",
    round(similarity_2, 4)
)

print("\nTEST TERMINE.")