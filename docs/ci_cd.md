# CI/CD — GitHub Actions

Dos workflows en `.github/workflows/`:

| Workflow | Trigger | Propósito |
|---|---|---|
| `tests.yml` | push/PR a `main` | Lint (ruff + black) y tests (pytest + coverage) |
| `deploy.yml` | `workflow_dispatch` (manual) | Desplegar Lambda ingesta, sync script Spark a S3, `zappa update` de la API |

---

## 1. `tests.yml` — CI

Dos jobs en `ubuntu-latest`:

1. **lint** — `uv sync --group dev` → `ruff check .` → `black --check .`.
2. **test** — depende de lint, instala extras necesarias (excepto `spark` porque pyspark no se testea localmente: necesita Java) y ejecuta `pytest --cov`. El reporte XML se sube como artifact.

Usa `astral-sh/setup-uv@v3` con cache de `uv.lock` para acelerar reruns.

## 2. `deploy.yml` — CD

> **Limitación del AWS Academy Learner Lab**: las credenciales caducan cada ~4 horas. No se puede automatizar el deploy en push porque los secretos quedarían vencidos. El trigger es **`workflow_dispatch`** (manual): el estudiante refresca credenciales y dispara el deploy desde la pestaña Actions.

El workflow tiene un input `component` con opciones:

- `all` — los tres deploys en paralelo
- `lambda-ingest` — solo la Lambda de ingesta
- `spark-script` — solo `aws s3 sync spark_jobs/ s3://shopstream-processed-mf0106/code/`
- `api` — solo `zappa update dev` + inyección de `DB_PASSWORD`

### Jobs

- **deploy-lambda-ingest** — empaqueta con `uv pip install --python-platform x86_64-manylinux2014 --target build/lambda jsonschema` (cross-compile para AWS Lambda), zip, `aws lambda update-function-code`.
- **deploy-spark-script** — `aws s3 sync` del directorio `spark_jobs/` excluyendo notebooks y caches.
- **deploy-api** — crea un venv slim, ejecuta `zappa update dev`, luego `aws lambda update-function-configuration` para inyectar `DB_PASSWORD` (no se commitea en `zappa_settings.json`), termina con smoke test `curl /health`.

---

## 3. Secretos requeridos en GitHub

En **Settings → Secrets and variables → Actions → New repository secret** añade los 4 secretos siguientes y refréscalos antes de cada deploy:

| Secret | Origen | Notas |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | AWS Academy → Start Lab → AWS Details → AWS CLI Show | Caduca al cerrar el lab |
| `AWS_SECRET_ACCESS_KEY` | idem | idem |
| `AWS_SESSION_TOKEN` | idem | **obligatorio** en Learner Lab (no son creds permanentes) |
| `DB_PASSWORD` | `.env.local` | Password del usuario `shopstream_admin` de la RDS |

Atajo CLI para sincronizar los 3 primeros desde tu máquina (requiere `gh`):

```powershell
gh secret set AWS_ACCESS_KEY_ID --body "$env:AWS_ACCESS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY --body "$env:AWS_SECRET_ACCESS_KEY"
gh secret set AWS_SESSION_TOKEN --body "$env:AWS_SESSION_TOKEN"
```

`DB_PASSWORD` se setea una sola vez (la password de RDS no rota).

---

## 4. Branch protection en `main`

> **GitHub UI**: Settings → Branches → Add branch protection rule

Configuración recomendada para la rama `main`:

- **Branch name pattern**: `main`
- **Require a pull request before merging**: ON
  - Require approvals: 1 (si trabajas solo, puedes dejarlo en 0 y solo exigir status checks)
  - Dismiss stale pull request approvals when new commits are pushed: ON
- **Require status checks to pass before merging**: ON
  - Require branches to be up to date before merging: ON
  - Status checks requeridos:
    - `Lint (ruff + black)`
    - `Tests + coverage`
- **Require conversation resolution before merging**: ON
- **Do not allow bypassing the above settings**: ON (los administradores también deben cumplir)
- **Restrict who can push to matching branches**: opcional

> Los nombres de los status checks aparecen en el dropdown después de que el workflow `tests.yml` haya corrido **al menos una vez** en cualquier branch — si no aparecen, abre un PR de prueba primero.

---

## 5. Disparar un deploy

1. **Refresca credenciales del Learner Lab** y actualiza los 3 secretos AWS_* en GitHub.
2. Ve a la pestaña **Actions → deploy** del repo.
3. **Run workflow** → branch `main` → elige `component` → **Run**.
4. Monitorea los logs. Si la API se desplegó, el último step (`Smoke test`) imprime la URL de API Gateway.

---

## 6. Limitaciones conocidas

| Limitación | Workaround |
|---|---|
| Credenciales temporales caducan en 4h | Solo deploy manual; documentado arriba |
| No se puede crear roles IAM nuevos | Usar `LabRole` (ya configurado en `zappa_settings.json`) |
| Account ID hardcoded en `deploy.yml` (`980511866105`) y nombre de RDS | Cambiar al fork del proyecto |
| `pyspark` no se testea en CI (requiere Java) | Validado en EMR real, ver PLAN.md §3.10 |
