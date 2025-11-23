#!/usr/bin/env python3
"""
Test script to identify which date/time functions e6data supports.
This helps determine the correct time grain expressions for Superset integration.

Usage:
    python test_e6data_date_functions.py

Requirements:
    - Set environment variables: ENGINE_IP, DB_NAME, EMAIL, PASSWORD, CATALOG, PORT
    - Or modify the connection parameters in this script
"""

import os
from e6data_python_connector import Connection


def test_date_functions():
    """Test various date/time functions to see which ones e6data supports"""

    # Connection parameters - modify these or use environment variables
    host = os.getenv("ENGINE_IP", "your_host")
    port = int(os.getenv("PORT", "80"))
    username = os.getenv("EMAIL", "your_email")
    password = os.getenv("PASSWORD", "your_token")
    database = os.getenv("DB_NAME", "your_database")
    catalog = os.getenv("CATALOG", "your_catalog")

    print("=" * 80)
    print("E6DATA DATE/TIME FUNCTION COMPATIBILITY TEST")
    print("=" * 80)
    print()

    # Create connection
    try:
        conn = Connection(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            catalog=catalog
        )
        print("✓ Connection established successfully")
        print()
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        print("\nPlease set environment variables or modify the script:")
        print("  - ENGINE_IP: e6data cluster IP")
        print("  - PORT: e6data port (default: 80)")
        print("  - EMAIL: your e6data email")
        print("  - PASSWORD: your access token")
        print("  - DB_NAME: database name")
        print("  - CATALOG: catalog name")
        return

    # Test queries for different date functions
    test_queries = {
        "CURRENT_TIMESTAMP": "SELECT CURRENT_TIMESTAMP as result",
        "CURRENT_DATE": "SELECT CURRENT_DATE() as result",

        # DATE_TRUNC function (most common in modern SQL engines)
        "DATE_TRUNC (second)": "SELECT DATE_TRUNC('second', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (minute)": "SELECT DATE_TRUNC('minute', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (hour)": "SELECT DATE_TRUNC('hour', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (day)": "SELECT DATE_TRUNC('day', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (week)": "SELECT DATE_TRUNC('week', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (month)": "SELECT DATE_TRUNC('month', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (quarter)": "SELECT DATE_TRUNC('quarter', CURRENT_TIMESTAMP) as result",
        "DATE_TRUNC (year)": "SELECT DATE_TRUNC('year', CURRENT_TIMESTAMP) as result",

        # TRUNC function (Oracle-style)
        "TRUNC (day)": "SELECT TRUNC(CURRENT_TIMESTAMP, 'DD') as result",
        "TRUNC (month)": "SELECT TRUNC(CURRENT_TIMESTAMP, 'MM') as result",
        "TRUNC (year)": "SELECT TRUNC(CURRENT_TIMESTAMP, 'YYYY') as result",

        # DATE_FORMAT function (MySQL-style)
        "DATE_FORMAT (day)": "SELECT DATE_FORMAT(CURRENT_TIMESTAMP, '%Y-%m-%d') as result",
        "DATE_FORMAT (month)": "SELECT DATE_FORMAT(CURRENT_TIMESTAMP, '%Y-%m-01') as result",
        "DATE_FORMAT (year)": "SELECT DATE_FORMAT(CURRENT_TIMESTAMP, '%Y-01-01') as result",

        # CAST to DATE (simple truncation to day)
        "CAST AS DATE": "SELECT CAST(CURRENT_TIMESTAMP AS DATE) as result",

        # YEAR, MONTH, DAY functions
        "YEAR function": "SELECT YEAR(CURRENT_TIMESTAMP) as result",
        "MONTH function": "SELECT MONTH(CURRENT_TIMESTAMP) as result",
        "DAY function": "SELECT DAY(CURRENT_TIMESTAMP) as result",
        "QUARTER function": "SELECT QUARTER(CURRENT_TIMESTAMP) as result",
        "DAYOFWEEK function": "SELECT DAYOFWEEK(CURRENT_TIMESTAMP) as result",

        # Presto/Trino-style date_trunc
        "date_trunc (lowercase)": "SELECT date_trunc('day', CURRENT_TIMESTAMP) as result",

        # FROM_UNIXTIME (for epoch conversion)
        "FROM_UNIXTIME": "SELECT FROM_UNIXTIME(1609459200) as result",

        # TO_TIMESTAMP (string to timestamp)
        "TO_TIMESTAMP": "SELECT TO_TIMESTAMP('2023-01-01 12:00:00', 'YYYY-MM-DD HH24:MI:SS') as result",
    }

    results = {}
    cursor = conn.cursor()

    print("Testing date/time functions...")
    print("-" * 80)

    for func_name, query in test_queries.items():
        try:
            cursor.execute(query)
            result = cursor.fetchone()
            results[func_name] = {
                "status": "✓ SUPPORTED",
                "result": result[0] if result else None,
                "error": None
            }
            print(f"✓ {func_name:30s} | {result[0]}")
        except Exception as e:
            error_msg = str(e)
            results[func_name] = {
                "status": "✗ NOT SUPPORTED",
                "result": None,
                "error": error_msg[:80]  # Truncate error message
            }
            print(f"✗ {func_name:30s} | Error: {error_msg[:50]}...")

    cursor.close()
    conn.close()

    # Summary and recommendations
    print()
    print("=" * 80)
    print("RECOMMENDATIONS FOR SUPERSET ENGINE SPEC")
    print("=" * 80)
    print()

    # Determine which date truncation method works
    if results.get("DATE_TRUNC (day)", {}).get("status") == "✓ SUPPORTED":
        print("✓ E6data supports DATE_TRUNC function (Presto/Trino-style)")
        print()
        print("Use this in your Superset engine spec:")
        print("""
_time_grain_expressions = {
    None: "{col}",
    "PT1S": "DATE_TRUNC('second', {col})",
    "PT1M": "DATE_TRUNC('minute', {col})",
    "PT1H": "DATE_TRUNC('hour', {col})",
    "P1D": "DATE_TRUNC('day', {col})",
    "P1W": "DATE_TRUNC('week', {col})",
    "P1M": "DATE_TRUNC('month', {col})",
    "P3M": "DATE_TRUNC('quarter', {col})",
    "P1Y": "DATE_TRUNC('year', {col})",
}
""")
    elif results.get("TRUNC (day)", {}).get("status") == "✓ SUPPORTED":
        print("✓ E6data supports TRUNC function (Oracle-style)")
        print()
        print("Use this in your Superset engine spec:")
        print("""
_time_grain_expressions = {
    None: "{col}",
    "P1D": "TRUNC({col}, 'DD')",
    "P1M": "TRUNC({col}, 'MM')",
    "P1Y": "TRUNC({col}, 'YYYY')",
}
""")
    elif results.get("DATE_FORMAT (day)", {}).get("status") == "✓ SUPPORTED":
        print("✓ E6data supports DATE_FORMAT function (MySQL-style)")
        print()
        print("Use this in your Superset engine spec:")
        print("""
_time_grain_expressions = {
    None: "{col}",
    "PT1H": "DATE_FORMAT({col}, '%Y-%m-%d %H:00:00')",
    "P1D": "DATE_FORMAT({col}, '%Y-%m-%d')",
    "P1M": "DATE_FORMAT({col}, '%Y-%m-01')",
    "P1Y": "DATE_FORMAT({col}, '%Y-01-01')",
}
""")
    elif results.get("CAST AS DATE", {}).get("status") == "✓ SUPPORTED":
        print("✓ E6data supports CAST to DATE (basic truncation to day)")
        print()
        print("Note: This only provides day-level granularity")
        print("""
_time_grain_expressions = {
    None: "{col}",
    "P1D": "CAST({col} AS DATE)",
}
""")
    else:
        print("⚠ Warning: No standard date truncation functions detected")
        print("You may need to contact e6data support for date manipulation syntax")

    print()
    print("=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print()
    print("1. Review the results above to identify supported functions")
    print("2. Update SUPERSET_ENGINE_SPEC_SOLUTION.md with the correct expressions")
    print("3. Create /app/superset/db_engine_specs/e6data.py in your Superset installation")
    print("4. Restart Superset and test time-based charts")
    print()


if __name__ == "__main__":
    test_date_functions()