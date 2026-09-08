import argparse

from server import connect, latest_trade_date, load_strategy, store_rule_daily_results


def main():
    parser = argparse.ArgumentParser(description="Run active DB strategy rules for one EOD date and store per-stock results.")
    parser.add_argument("--date", help="Signal date in YYYY-MM-DD. Defaults to latest NSE date in SQLite.")
    args = parser.parse_args()

    trade_date = args.date or latest_trade_date()
    if not trade_date:
        raise SystemExit("No NSE trade date found in SQLite.")

    with connect() as conn:
        strategy = load_strategy(conn)
        rules = [rule for rule in strategy.get("rules", []) if rule.get("filters")]
        if not rules:
            raise SystemExit("No active rules found in SQLite. Start the app once or save strategy first.")
        stored = store_rule_daily_results(conn, trade_date, rules)
        conn.commit()

    print(f"EOD analysis complete for {trade_date}")
    print(f"Rules evaluated: {len(rules)}")
    print(f"Stored rule-stock results: {stored:,}")


if __name__ == "__main__":
    main()
