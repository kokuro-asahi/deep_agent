conda activate deepagent
cd /opt/Workspace/CRX/deepagent_interface
/opt/miniconda3/envs/deepagent/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8010


export GIT_DIR=.git-local
export GIT_WORK_TREE=.