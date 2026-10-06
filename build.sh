#!/bin/sh
# Construit dist/jiji.pyz : application en un seul fichier (nécessite Python 3.11+ sur le poste).
set -e
cd "$(dirname "$0")"
rm -rf build dist && mkdir -p build dist
cp -r jiji build/jiji && find build -name __pycache__ -prune -exec rm -rf {} +
rm -f build/jiji/demo.py
python3 -m zipapp build -m "jiji.__main__:main" -p "/usr/bin/env python3" -c -o dist/jiji.pyz
rm -rf build
echo "OK : dist/jiji.pyz"
