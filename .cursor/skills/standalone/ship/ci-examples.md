# CI Configuration Examples

## GitHub Actions — Main Pipeline

```yaml
name: CI Pipeline

on:
  pull_request:
    branches: [main, staging]
  push:
    branches: [main, staging]

jobs:
  lint-and-type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff mypy
      - run: ruff check .
      - run: mypy src/

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: test_db
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest tests/ --junitxml=results.xml -v
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379

  ai-evals:
    runs-on: ubuntu-latest
    if: contains(github.event.pull_request.labels.*.name, 'ai-change')
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest tests/ai_evals/ --junitxml=eval-results.xml
        env:
          AI_EVAL_MODE: ci

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install bandit safety
      - run: bandit -r src/ -f json -o bandit-report.json || true
      - run: safety check --json > safety-report.json || true

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend/
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
      - run: npm run lint
      - run: npm run type-check
      - run: npm run test
```

## Database Migration Validation

```yaml
  migration-check:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: migration_test
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - run: pip install alembic psycopg2-binary sqlalchemy
      - name: Test upgrade
        run: alembic upgrade head
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/migration_test
      - name: Test downgrade
        run: alembic downgrade -1
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/migration_test
      - name: Re-upgrade (idempotency)
        run: alembic upgrade head
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/migration_test
```

## Deploy Staging (on merge to staging)

```yaml
name: Deploy Staging

on:
  push:
    branches: [staging]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to Railway (staging)
        run: railway up --environment staging
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
      - name: Smoke test
        run: |
          sleep 30
          curl --fail https://staging.posai.app/health
      - name: Notify
        if: failure()
        run: echo "Staging deploy failed" # Replace with Slack/Discord notification
```
