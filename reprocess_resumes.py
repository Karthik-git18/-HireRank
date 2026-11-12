"""Recalculate stored resume analysis without changing application IDs or PDF files."""
import argparse

from app import create_app
from modules.database import get_db, init_db
from modules.reprocessing import reprocess_existing_applications


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist refreshed analysis; default is dry-run.")
    parser.add_argument("--user-id", type=int, help="Limit reprocessing to one HR account ID.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        init_db()
        db = get_db()
        try:
            results = reprocess_existing_applications(
                db, app.config["UPLOAD_FOLDER"], user_id=args.user_id, dry_run=not args.apply
            )
            if args.apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
        detected = sum(result["name_detected"] for result in results)
        print(
            f"{'Updated' if args.apply else 'Dry run'}: {len(results)} applications; "
            f"{detected} names detected, {len(results) - detected} names not detected. "
            f"{'No application or PDF records were inserted or deleted.' if args.apply else 'Use --apply to persist.'}"
        )


if __name__ == "__main__":
    main()
