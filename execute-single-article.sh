#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR

./pylint.sh
venv/bin/py.test -v -s spectrum/test_article.py::test_article_first_version --article-id=$1 --assert=plain

