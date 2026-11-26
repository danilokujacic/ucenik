#!/usr/bin/env bash
# Creates k8s/overlays/local/secrets.env (gitignored) for the local minikube
# stack: random hex for every generated credential, and GROQ_API_KEY /
# HF_API_KEY copied from the repo-root .env if they're set there.
#
# Never overwrites an existing file - MongoDB only reads its root password on
# the very first start, so silently rotating it would lock the app out of the
# existing data volume. Delete the file yourself (and the mongodb PVC) to
# start over.
set -euo pipefail

cd "$(dirname "$0")/.."
target=k8s/overlays/local/secrets.env

if [[ -f "$target" ]]; then
    echo "$target already exists - leaving it alone"
    exit 0
fi

rand() { openssl rand -hex 24; }

# Value of KEY from the root .env, or empty. Only exact `KEY=value` lines.
from_dotenv() {
    [[ -f .env ]] || return 0
    grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true
}

umask 077 # readable only by you
cat > "$target" <<EOF
JWT_SECRET=$(rand)
MONGO_USERNAME=admin
MONGO_PASSWORD=$(rand)
S3_ACCESS_KEY=ucenik
S3_SECRET_KEY=$(rand)
LLM_PROXY_API_KEY=$(rand)
EMBEDDING_SERVICE_API_KEY=$(rand)
GROQ_API_KEY=$(from_dotenv GROQ_API_KEY)
HF_API_KEY=$(from_dotenv HF_API_KEY)
EOF

echo "wrote $target"
if ! grep -qE '^(GROQ|HF)_API_KEY=.+' "$target"; then
    echo "note: GROQ_API_KEY and HF_API_KEY are both empty - LLM calls will fail until you set one and re-run 'make k8s-apply'"
fi
