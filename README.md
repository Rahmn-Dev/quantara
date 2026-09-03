# Quantara IDX

<img width="1920" height="1280" alt="121_1x_shots_so" src="https://github.com/user-attachments/assets/a5678034-f7b5-48f8-9c07-a2d1ec36ff79" />


Personal, deterministic-first IDX decision dashboard. The system deliberately separates:

`market data → quant score → risk veto → trade plan → WebSocket UI → AI explanation`

The LLM cannot override entry, stop, position size, daily-loss limit, or a failed setup.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000> and select **Run market scan**. SQLite and an in-memory
channel layer are the zero-setup development defaults. PostgreSQL + Redis + Daphne +
Celery are supplied in `docker-compose.yml` for the production-shaped runtime.

## Real market scan

The default dashboard scan is no longer a fixture. It downloads adjusted daily OHLCV
for the configured `.JK` universe, persists every candle, derives momentum, relative
volume, VWAP distance, ATR, liquidity and opening-gap features, evaluates the IHSG
regime from `^JKSE`, and then applies hard risk gates.

```bash
python manage.py load_idx_universe
python manage.py run_quant_scan --equity 100000000
```

Yahoo data is suitable for personal research and may be delayed. It is not an official
IDX realtime feed. Broker flow is currently neutral because no licensed broker-summary
source has been connected. Do not present the output as execution-grade until the
strategy passes walk-forward and paper-trading validation with fees and slippage.

## Safety contract

- `trading/engine.py` owns mathematical scoring and risk gates.
- A plan is `READY` only when every hard check passes.
- AI commentary is stored separately and cannot mutate checks.
- Demo snapshots are synthetic; replace `DEMO_MARKET` through a licensed IDX data adapter.
- Validate with transaction costs, slippage, survivorship-bias-free data, and walk-forward tests.

## Next production integrations

1. Licensed EOD + 1m/5m/15m OHLCV adapter and corporate-action normalization.
2. Broker summary and catalyst/news adapters with source timestamps.
3. TimescaleDB candle schema, idempotent ingestion, freshness/quality alarms.
4. Event-driven opening validation and paper-trade execution journal.
5. Walk-forward experiment registry; strategy promotion only after out-of-sample gates.
