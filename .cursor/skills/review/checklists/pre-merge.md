# Pre-Merge Checklist

Apply before any PR merge.

## Correctness
- [ ] Logic handles all identified edge cases
- [ ] Boundary values tested (empty, null, max, negative)
- [ ] Race conditions considered for concurrent paths
- [ ] Idempotency preserved on retry-able operations

## Reliability
- [ ] All external calls have timeouts
- [ ] Retry logic with exponential backoff on transient failures
- [ ] Fallback/degradation path exists for critical dependencies
- [ ] Errors are caught, logged, and re-raised appropriately

## Security
- [ ] All user inputs sanitized and validated
- [ ] No secrets in source code
- [ ] Auth/authz checks on new endpoints
- [ ] SQL injection, XSS, SSRF vectors eliminated

## Observability
- [ ] Structured logging on error paths (with correlation ID)
- [ ] New endpoints instrumented (latency, error rate)
- [ ] No PII/secrets in log output
- [ ] Alerts configured for new critical paths

## Performance
- [ ] No N+1 query patterns
- [ ] Queries use appropriate indexes
- [ ] Results are paginated/limited
- [ ] Expensive computations cached where appropriate

## Tests
- [ ] Unit tests for business logic
- [ ] Integration tests for service boundaries
- [ ] Happy path + error path coverage
- [ ] Tests are deterministic (no flaky tests)

## Documentation
- [ ] API changes reflected in contracts/OpenAPI
- [ ] Schema changes have migration scripts
- [ ] Non-obvious decisions documented (ADR or inline)
