# Main Gate Policy

## Trigger boundary

- GitHub Actions does not run for pull requests or ordinary feature-branch pushes.
- `.github/workflows/main-gate.yml` runs automatically only after `main` is updated.
- Repository-level manual runs are allowed only against `main`; selecting another ref fails in the lightweight validation job before project tests allocate their normal workload.
- Superseded automatic `main` runs may be cancelled because the current `main` state is the authoritative result. Manual runs use a unique concurrency group and are not cancelled by later pushes.

## Validation scope

The gate initializes only the submodules required by regular business tests:

```text
submodules/common
submodules/pokeapi
```

The sprites submodule is intentionally excluded from the routine gate because it is a large import asset rather than a normal unit/integration-test dependency.

The gate validates:

```bash
python -m pytest tests
cd web && npm test
cd web && npm run build
```

Use local tests and the repository's four-stage workflow while developing. Do not use GitHub Actions as a branch-level debugging loop.

## Failure email

Automatic `main` failures are visible in GitHub but do not send SMTP mail. Email is sent only when a manual `main` run fails.

The following repository secrets are required for that notification path:

- `SMTP_CONNECTION_URL`
- `MAIL_FROM`
- `MAIL_TO`
