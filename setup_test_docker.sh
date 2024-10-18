#!/usr/bin/env bash

# bash strict mode
set -euo pipefail

# TARGETARCH should be set automatically on most (but not all) systems, see
# https://github.com/princeton-nlp/SWE-agent/issues/245
docker build -t swe-rex-test:latest -f swe_rex_test.Dockerfile --build-arg TARGETARCH=$(uname -m) .

