# API Endpoint Checklist

Apply when adding or modifying REST/WebSocket endpoints.

## Design
- [ ] RESTful resource naming (nouns, not verbs)
- [ ] Appropriate HTTP method (GET=read, POST=create, PUT=replace, PATCH=update, DELETE=remove)
- [ ] Consistent response envelope structure
- [ ] Pagination for list endpoints (cursor-based preferred)
- [ ] Versioning strategy followed (URL prefix or header)

## Input Validation
- [ ] Request body validated against schema (Pydantic model)
- [ ] Path/query parameters typed and bounded
- [ ] File uploads size-limited and type-checked
- [ ] Malformed input returns 400 with descriptive error

## Auth & Security
- [ ] Authentication required (unless explicitly public)
- [ ] Authorization checks (role/permission-based)
- [ ] Rate limiting configured
- [ ] CORS policy appropriate
- [ ] No sensitive data in URL query parameters

## Error Handling
- [ ] Consistent error response format (`{"error": {"code": ..., "message": ...}}`)
- [ ] Appropriate HTTP status codes (don't abuse 200 for errors)
- [ ] Internal errors don't leak implementation details
- [ ] Timeout handling for downstream calls

## Observability
- [ ] Request/response logging (sanitized)
- [ ] Latency histogram metric
- [ ] Error rate counter
- [ ] Correlation ID propagated

## Documentation
- [ ] OpenAPI/Swagger spec updated
- [ ] Example request/response in docs
- [ ] Error codes documented
- [ ] Breaking changes flagged
