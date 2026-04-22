"""Legacy DB fixer placeholder.

SQLite local DB mutation has been removed from this project.
Use canonical PostgreSQL migrations and bootstrap commands instead.
"""

import sys


def main() -> int:
    print("SQLite local DB fixer has been removed.")
    print("Run canonical setup instead:")
    print("  python manage.py migrate")
    print("  python manage.py bootstrap_postgres_config")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
