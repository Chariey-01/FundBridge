# FundBridge
An AI-powered global crowdfunding platform connecting international donors with beneficiaries through accessible local payout channels.

## Backend

The Flask API lives in `backend/`. It uses fixed-precision decimals for money;
provider simulators never confirm a transaction without an explicit callback.

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app run.py db upgrade
flask --app run.py run
pytest
```

See [`backend/README.md`](backend/README.md) for configuration and simulator limitations.
