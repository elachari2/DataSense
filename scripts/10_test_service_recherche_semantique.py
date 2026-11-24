
"""DataSense - Test real de recherche semantique via le service."""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.services.semantic_search_service import (
    get_semantic_search_service
)


def main():
    print("=" * 65)
    print("DATASENSE - TEST DU SERVICE DE RECHERCHE SEMANTIQUE")
    print("=" * 65)

    question = input("\nSaisissez votre question en français : ").strip()

    if not question:
        print("Erreur : la question ne peut pas être vide.")
        return

    top_k_input = input("Nombre de commentaires à retourner [5] : ").strip()

    try:
        top_k = int(top_k_input) if top_k_input else 5

        service = get_semantic_search_service()

        print("\nRecherche en cours...")
        results = service.search(question, top_k=top_k)

        print("\nRÉSULTATS DE LA RECHERCHE")
        print("-" * 65)

        if not results:
            print("Aucun commentaire trouvé.")
            return

        for index, result in enumerate(results, start=1):
            print(f"\n{index}. Similarité : {result['similarity']:.4f}")
            print(f"Review ID : {result['review_id']}")
            print(f"Order ID : {result['order_id']}")
            print(f"Commentaire : {result['review_text']}")

        print(f"\nNombre de résultats : {len(results)}")

    except ValueError as error:
        print(f"\nErreur de saisie : {error}")
    except Exception as error:
        print(f"\nErreur pendant la recherche : {error}")


if __name__ == "__main__":
    main()
