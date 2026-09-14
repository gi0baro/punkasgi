#!/usr/bin/env bash
# Builds the environment and runs every benchmark section. Run from the repo root.

set -euo pipefail

rm -rf ./bench/.envs
mkdir -p ./bench/.envs

uv venv -p 3.14t ./bench/.envs/.venv314t
VIRTUAL_ENV=$(pwd)/bench/.envs/.venv314t uv pip install -r ./bench/envs/py314t.txt
VIRTUAL_ENV=$(pwd)/bench/.envs/.venv314t uv pip install .

cd ./bench

export BENCHMARK_BIN=$(pwd)/.envs/.venv314t/bin

./.envs/.venv314t/bin/python benchmarks.py
