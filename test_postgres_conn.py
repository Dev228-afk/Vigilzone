import psycopg2
from psycopg2.extras import RealDictCursor


def test_postgres_connection_fetch_records(
    host: str = "localhost",
    port: int = 5432,
    database: str = "postgres",
    user: str = "postgres",
    password: str = "dev",
    limit: int = 5,
) -> None:
    """Connect to PostgreSQL and fetch sample records to verify connectivity.

    Defaults target:
    - host: localhost
    - port: 5432
    - database: postgres
    - password: dev
    """
    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            connect_timeout=5,
        )

        print("PostgreSQL connection: SUCCESS")

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Fetch sample rows from a guaranteed system catalog view.
            cursor.execute(
                """
                SELECT schemaname, tablename
                FROM pg_catalog.pg_tables
                ORDER BY schemaname, tablename
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        print(f"Fetched {len(rows)} sample record(s) from {database}:")
        for idx, row in enumerate(rows, start=1):
            print(f"{idx}. {row}")

    except Exception as exc:
        print(f"PostgreSQL connection/fetch FAILED: {exc}")
    finally:
        if conn is not None:
            conn.close()
            print("PostgreSQL connection: CLOSED")


if __name__ == "__main__":
    test_postgres_connection_fetch_records()
