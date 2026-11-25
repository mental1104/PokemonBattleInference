# Main Gate Policy

## Trigger boundary

- A non-draft pull request targeting `main` runs the project gate before merge. Draft PRs create no test workload; `ready_for_review` starts the first validation, and later synchronizations replace stale runs.
- Ordinary feature-branch pushes do not run GitHub Actions.
- `.github/workflows/main-gate.yml` also runs automatically after `main` is updated.
- Repository-level manual runs are allowed only against `main`; selecting another ref fails in the lightweight validation job before project tests allocate their normal workload.
- Superseded PR and automatic `main` runs may be cancelled because only the latest state is authoritative. Manual runs use a unique concurrency group and are not cancelled by later pushes.

## Validation scope

The gate initializes only the submodules required by regular business tests:

```text
submodules/common
submodules/pokeapi
```

The repository keeps developer-facing SSH URLs in `.gitmodules`. GitHub-hosted runners override only these two checkout-local submodule URLs to HTTPS because they have a repository token but no developer SSH key.

The sprites submodule is intentionally excluded from the routine gate because it is a large import asset rather than a normal unit/integration-test dependency.

The same pre-merge and post-merge gate validates:

```bash
python -m pytest tests
cd web && npm test
cd web && npm run build
```

Use local tests and the repository's four-stage workflow while developing. GitHub Actions is the Ready PR correctness gate and the integrated `main` verification, not an uncontrolled branch-level debugging loop.

## Monorepo migration validation

The separately authorized `native-core.yml` validates native Core/Go/Swift and unsigned iOS device/simulator targets on a Ready PR. Its App and simulator results do not constitute physical-device acceptance. Missing external integration environments remain explicit SKIP results.

The independent `deploy/compose.go-runtime.yaml` and `make go-compose-*` prepare the Go/C++ runtime under the distinct `pokemon-go-preview` project. They do not change the legacy Compose default. `tools/migration/validate-go-stack.sh` runs the isolated Vue/API/Worker/PG browser, health, rollback and restore scenarios; complete sprites remain an explicit read-only asset input rather than a routine CI checkout.

Legacy database adoption is an explicit `pbi-db-init --adopt-legacy-knowledge` operation after complete fixed-source/schema/data verification. The default initializer must continue rejecting unversioned nonempty targets. `tools/migration/accept-go-legacy-adoption.sh` validates the real Python-to-Go path only on its own temporary PostgreSQL instance; its five-image preservation fixture does not replace full-corpus acceptance. See `docs/go-runtime.md` and `docs/migration-progress.md` for actual verified scope and remaining Human approval items.

## Failure email

Automatic PR and `main` failures are visible in GitHub but do not send SMTP mail. Email is sent only when a manual `main` run fails.

The following repository secrets are required for that notification path:

- `SMTP_CONNECTION_URL`
- `MAIL_FROM`
- `MAIL_TO`
