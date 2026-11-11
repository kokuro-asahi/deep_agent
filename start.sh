#!/usr/bin/env bash
set -euo pipefail

cd /opt/Workspace/CRX/deepagent_interface
exec conda run --no-capture-output -n deepagent_0734 python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8089}"



export GIT_DIR=.git-local
export GIT_WORK_TREE=.