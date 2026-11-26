# Kubernetes

The whole stack - API, Celery worker, LLM proxy, embedding service, frontend,
and Mongo/Redis/Chroma/MinIO - as Kubernetes manifests, organized with
Kustomize. This replaces the old `docker-compose.prod.yaml` + nginx-certbot
deploy. Local development still uses `docker compose up` for infra plus the
app on your host (root README); this folder is for running everything
containerized.

So far there is one environment: **local**, on minikube.

## Layout

```
k8s/
  base/                       same in every environment
    kustomization.yaml        lists resources + generates the ucenik-config ConfigMap
    namespace.yaml            everything lives in namespace `ucenik`
    networkpolicies.yaml      deny-by-default + who may talk to whom
    data/                     StatefulSets: mongodb, redis, chromadb, minio
    services/                 Deployments: api, worker, llm-proxy, embedding-service, frontend
  overlays/
    local/                    minikube: image tags, hostnames, Ingress, secrets
      secrets.env.example     template - the real secrets.env is gitignored
```

An **overlay** is "base, plus these changes". `kubectl apply -k
k8s/overlays/local` builds base, applies the local changes on top, and sends
the result to the cluster. To see exactly what would be applied, without
applying it:

```bash
kubectl kustomize k8s/overlays/local | less
```

## Running it locally

Needs Docker and minikube. The cluster takes 8GB RAM / 6 CPUs - mostly for the
embedding service (BGE-M3 alone is ~2.5GB).

```bash
make k8s-up        # 1. start a minikube cluster (profile "ucenik") with Calico + ingress-nginx
make k8s-build     # 2. build both images inside minikube (first run is slow: downloads BGE-M3)
make k8s-apply     # 3. create secrets.env if missing, then apply the local overlay
make k8s-status    # 4. watch pods until everything is Running and READY 1/1
make k8s-forward   # 5. (leave running) expose the ingress on localhost:8080
```

Then open:

- frontend: <http://ucenik.localhost:8080>
- API: <http://api.ucenik.localhost:8080/docs> (Swagger - local overlay sets `ENVIRONMENT=development`)

`*.localhost` always resolves to your own machine, so there's no `/etc/hosts`
editing.

Seed the demo users (`teacher@ucenik.dev` / `student@ucenik.dev`, password
`ucenik123`) the same way as in the root README, but inside the api pod:

```bash
kubectl --context ucenik -n ucenik exec deploy/api -- uv run ucenik-seed
```

Stop with `make k8s-down` (keeps data) or `make k8s-delete` (deletes the
cluster and **all data in it**).

### After changing code

The images are tagged `:local`, so the Deployment spec doesn't change when you
rebuild and Kubernetes won't notice on its own. Rebuild, then restart:

```bash
make k8s-build
kubectl --context ucenik -n ucenik rollout restart deploy/api deploy/worker
```

## How a request travels - worked example

Say the browser loads a subject's documents:

1. The browser calls `http://api.ucenik.localhost:8080/subjects/42/documents`.
   (`NEXT_PUBLIC_API_URL` was baked into the frontend at `make k8s-build`.)
2. `*.localhost` -> 127.0.0.1:8080 -> `kubectl port-forward` -> the
   **ingress-nginx controller** pod (namespace `ingress-nginx`).
3. The controller reads `overlays/local/ingress.yaml`: host
   `api.ucenik.localhost` -> Service `api`, port 8000.
4. The **NetworkPolicy** `allow-from-ingress-controller` lets that connection
   in. Everything else in the namespace is closed by `default-deny-ingress`.
5. Service `api` forwards to the `api` pod. The pod reads documents from
   `mongodb:27017`, which works because `data-stores-from-backend` allows
   api/worker -> data stores.

If the frontend pod tried to connect to `mongodb:27017` directly, the
connection would just hang and time out: no policy allows frontend -> mongodb.
You can test that:

```bash
kubectl --context ucenik -n ucenik exec deploy/frontend -- \
  node -e "require('net').connect(27017,'mongodb').on('connect',()=>console.log('OPEN')).setTimeout(3000,()=>{console.log('BLOCKED');process.exit()})"
```

## Configuration and secrets

Two sources, both injected as environment variables (the same names as
`.env.example`, so the Python settings classes need no changes):

| What | Where | Example |
|---|---|---|
| Non-secret settings | `configMapGenerator` in `base/kustomization.yaml`, overridden per overlay | `REDIS_URL=redis://redis:6379` |
| Secrets | `overlays/local/secrets.env` -> `secretGenerator` | `JWT_SECRET`, `MONGO_PASSWORD`, `GROQ_API_KEY` |

- Each pod gets **only the secret keys it uses** (e.g. only `llm-proxy` gets
  `GROQ_API_KEY`), listed one by one under `env:`.
- `MONGODB_URL` is composed in the manifest:
  `mongodb://$(MONGO_USERNAME):$(MONGO_PASSWORD)@mongodb:27017/...`. Kubernetes
  fills in `$(...)` from variables defined earlier in the same list, so the
  password exists in one place only.
- Generated names get a content hash (`ucenik-secrets-64dk8kc289`). Edit
  `secrets.env`, run `make k8s-apply`, and the name changes, so every pod
  using it restarts with the new values. A plain Secret edit would leave
  running pods on the old values.

To add an LLM key: put `GROQ_API_KEY=...` (or `HF_API_KEY`) in
`overlays/local/secrets.env` and run `make k8s-apply`.

**Don't change `MONGO_PASSWORD` after the first start.** Mongo only reads it
when its data volume is empty, so changing it later locks the app out. To
start over, delete the volume: `kubectl --context ucenik -n ucenik delete
statefulset/mongodb pvc/data-mongodb-0`, then `make k8s-apply`.

## Data

Each data store is a StatefulSet with a PersistentVolumeClaim
(`data-mongodb-0`, `data-minio-0`, ...). Data survives pod restarts,
`kubectl delete pod`, and `make k8s-down`. Only deleting the PVC or the
cluster (`make k8s-delete`) loses it.

## Not done yet

- **A real cluster + deploy from CI.** CI builds and pushes images to GHCR and
  validates these manifests (`.github/workflows/k8s-validate.yml`), but deploys
  nowhere. Next: an `overlays/prod` (GHCR images, real hostname, TLS via
  cert-manager), and a CI job running `kubectl apply -k k8s/overlays/prod`
  with the commit's image tag, using a `KUBECONFIG` secret.
- **Backups.** `backup/*.sh` ran as compose services; they should become
  CronJobs.
- **Logs/metrics.** Loki/Promtail/Grafana are still compose-only.
- **Ingress controller choice for prod.** Locally this uses minikube's
  ingress-nginx addon. The ingress-nginx project has been retired upstream, so
  a production cluster should use a maintained controller (e.g. Traefik or
  a Gateway API implementation). Only `overlays/*/ingress.yaml` and
  `networkpolicy-ingress.yaml` depend on that choice.
