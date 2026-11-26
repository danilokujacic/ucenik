# Local dev process runners. Each backend service (main API, Celery worker,
# LLM proxy, embedding service) runs as its own foreground process in its
# own terminal - see README.md for the main API (`uv run fastapi dev`, not
# duplicated here since it's the one already documented there). These wrap
# the exact commands documented in workers/celery_app.py's,
# llm_proxy/main.py's, and embedding_service/main.py's own docstrings, so
# there's one obvious way to start them instead of everyone retyping (and
# inevitably drifting from) the same long command.

.PHONY: celery llm-proxy embedding-service

celery:
	./scripts/run-celery.sh

llm-proxy:
	./scripts/run-llm-proxy.sh

embedding-service:
	./scripts/run-embedding-service.sh

# --- Local Kubernetes (minikube) ---------------------------------------------
# Whole stack on a local cluster - see k8s/README.md for the walkthrough.
# Separate minikube profile so it never touches your default `minikube`
# cluster. Docker runtime (so `minikube docker-env` works and images are built
# straight into the node), Calico (so NetworkPolicies are actually enforced).
K8S_PROFILE := ucenik
KUBECTL := kubectl --context $(K8S_PROFILE)
FRONTEND_PUBLIC_API_URL := http://api.ucenik.localhost:8080

.PHONY: k8s-up k8s-build k8s-secrets k8s-apply k8s-status k8s-forward k8s-down k8s-delete

k8s-up:
	minikube start -p $(K8S_PROFILE) --driver=docker --container-runtime=docker \
		--cni=calico --memory=8g --cpus=6 --addons=ingress

# Builds into minikube's own Docker daemon (eval docker-env), not your host's.
k8s-build:
	eval $$(minikube -p $(K8S_PROFILE) docker-env) && \
		docker build -t ucenik-backend:local . && \
		docker build -t ucenik-frontend:local \
			--build-arg NEXT_PUBLIC_API_URL=$(FRONTEND_PUBLIC_API_URL) frontend

k8s-secrets:
	./scripts/k8s-local-secrets.sh

k8s-apply: k8s-secrets
	$(KUBECTL) apply -k k8s/overlays/local

k8s-status:
	$(KUBECTL) -n ucenik get pods,svc,pvc,ingress

# Frontend: http://ucenik.localhost:8080   API: http://api.ucenik.localhost:8080
k8s-forward:
	$(KUBECTL) -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80

k8s-down:
	minikube stop -p $(K8S_PROFILE)

# Deletes the cluster *and all its data* (Mongo, MinIO, Chroma volumes).
k8s-delete:
	minikube delete -p $(K8S_PROFILE)
