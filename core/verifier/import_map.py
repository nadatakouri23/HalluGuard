"""
Static knowledge shared by the verifiers.

* ``IMPORT_TO_DIST`` – Python *import* name -> PyPI *distribution* name
  (``cv2 -> opencv-python``).  The two namespaces differ, so querying PyPI with
  the import name is wrong for these packages.
* ``DIST_NAME_NOT_IMPORTABLE`` – distribution names that people (and LLMs)
  wrongly use in an ``import`` statement (``import pillow``).  They *exist* on
  PyPI, so a registry lookup alone would accept them.
* ``REMOVED_STDLIB`` – modules removed from recent Pythons; code written for
  older versions is still valid, so they are treated as standard library.
* ``OFFLINE_*`` – curated sets of well-known packages, the only positive
  evidence available in offline mode.
"""
from __future__ import annotations

import re

IMPORT_TO_DIST: dict[str, str] = {
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "attr": "attrs",
    "jwt": "pyjwt",
    "jose": "python-jose",
    "OpenSSL": "pyopenssl",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodomex",
    "serial": "pyserial",
    "usb": "pyusb",
    "magic": "python-magic",
    "git": "gitpython",
    "MySQLdb": "mysqlclient",
    "psycopg2": "psycopg2-binary",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "pymupdf",
    "zmq": "pyzmq",
    "nacl": "pynacl",
    "wx": "wxpython",
    "gi": "pygobject",
    "dns": "dnspython",
    "bson": "pymongo",
    "slugify": "python-slugify",
    "socks": "pysocks",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "pkg_resources": "setuptools",
    "mpl_toolkits": "matplotlib",
    "ldap": "python-ldap",
    "flask_cors": "flask-cors",
    "flask_sqlalchemy": "flask-sqlalchemy",
    "flask_login": "flask-login",
    "flask_migrate": "flask-migrate",
    "flask_wtf": "flask-wtf",
    "rest_framework": "djangorestframework",
    "discord": "discord.py",
    "telegram": "python-telegram-bot",
    "cairo": "pycairo",
    "OpenGL": "pyopengl",
    "Xlib": "python-xlib",
    "faiss": "faiss-cpu",
    "grpc": "grpcio",
    "googleapiclient": "google-api-python-client",
    "ruamel": "ruamel.yaml",
    "pythonjsonlogger": "python-json-logger",
    "_pytest": "pytest",
}

DIST_NAME_NOT_IMPORTABLE: dict[str, str] = {
    "pillow": "PIL",
    "pyyaml": "yaml",
    "scikit_learn": "sklearn",
    "scikit_image": "skimage",
    "beautifulsoup": "bs4",
    "beautifulsoup4": "bs4",
    "opencv": "cv2",
    "opencv_python": "cv2",
    "python_dotenv": "dotenv",
    "python_dateutil": "dateutil",
    "python_docx": "docx",
    "python_pptx": "pptx",
    "pyjwt": "jwt",
    "pycryptodome": "Crypto",
}

REMOVED_STDLIB: frozenset[str] = frozenset({
    "aifc", "asynchat", "asyncore", "audioop", "cgi", "cgitb", "chunk",
    "crypt", "distutils", "imghdr", "imp", "lib2to3", "mailcap", "msilib",
    "nis", "nntplib", "ossaudiodev", "pipes", "smtpd", "sndhdr", "spwd",
    "sunau", "telnetlib", "uu", "xdrlib",
})

OFFLINE_KNOWN_PYPI: frozenset[str] = frozenset({
    "requests", "urllib3", "certifi", "idna", "charset-normalizer", "numpy",
    "pandas", "scipy", "matplotlib", "seaborn", "plotly", "scikit-learn",
    "scikit-image", "statsmodels", "sympy", "torch", "torchvision",
    "tensorflow", "keras", "jax", "transformers", "datasets", "tokenizers",
    "huggingface-hub", "openai", "anthropic", "langchain", "tiktoken",
    "flask", "django", "fastapi", "starlette", "uvicorn", "gunicorn",
    "aiohttp", "httpx", "websockets", "pydantic", "sqlalchemy", "alembic",
    "psycopg2-binary", "pymongo", "redis", "celery", "boto3", "botocore",
    "pytest", "tox", "black", "ruff", "mypy", "flake8", "pylint", "isort",
    "click", "typer", "rich", "tqdm", "colorama", "pyyaml", "toml", "tomli",
    "jinja2", "markupsafe", "werkzeug", "beautifulsoup4", "lxml", "scrapy",
    "selenium", "playwright", "pillow", "opencv-python", "imageio", "pygame",
    "pytz", "python-dateutil", "arrow", "pendulum", "python-dotenv", "attrs",
    "cryptography", "pyjwt", "passlib", "bcrypt", "paramiko", "pyopenssl",
    "setuptools", "wheel", "pip", "virtualenv", "poetry", "packaging",
    "typing-extensions", "six", "decorator", "cachetools", "tenacity",
    "joblib", "numba", "dask", "pyarrow", "polars", "networkx", "nltk",
    "spacy", "gensim", "xgboost", "lightgbm", "catboost", "tree-sitter",
    "docker", "kubernetes", "ansible", "fabric", "psutil", "watchdog",
    "pyserial", "pexpect", "sh", "jsonschema", "marshmallow", "orjson",
    "ujson", "msgpack", "protobuf", "grpcio", "pyzmq", "openpyxl",
    "xlrd", "xlsxwriter", "python-docx", "pypdf", "reportlab", "markdown",
})

OFFLINE_KNOWN_NPM: frozenset[str] = frozenset({
    "express", "koa", "fastify", "hapi", "react", "react-dom", "next", "vue",
    "nuxt", "svelte", "angular", "@angular/core", "preact", "solid-js",
    "typescript", "ts-node", "tsx", "babel", "@babel/core", "webpack", "vite",
    "rollup", "esbuild", "parcel", "eslint", "prettier", "jest", "mocha",
    "chai", "sinon", "vitest", "cypress", "playwright", "puppeteer",
    "lodash", "underscore", "ramda", "moment", "dayjs", "date-fns", "axios",
    "node-fetch", "got", "superagent", "cors", "helmet", "morgan", "dotenv",
    "body-parser", "cookie-parser", "multer", "passport", "jsonwebtoken",
    "bcrypt", "bcryptjs", "mongoose", "sequelize", "prisma", "@prisma/client",
    "typeorm", "knex", "pg", "mysql2", "redis", "ioredis", "socket.io",
    "ws", "chalk", "commander", "yargs", "inquirer", "ora", "debug", "uuid",
    "zod", "joi", "yup", "ajv", "rxjs", "redux", "@reduxjs/toolkit", "mobx",
    "zustand", "swr", "tailwindcss", "postcss", "autoprefixer", "sass",
    "nodemon", "pm2", "concurrently", "cross-env", "rimraf", "glob",
    "fs-extra", "semver", "minimist", "cheerio", "marked", "handlebars",
    "ejs", "pug", "nodemailer", "winston", "pino", "@actions/core",
    "@actions/github", "@actions/exec", "@types/node", "react-router-dom",
    "@nestjs/common", "@nestjs/core", "graphql", "apollo-server",
})

_PEP503 = re.compile(r"[-_.]+")


def normalize_dist(name: str) -> str:
    """PEP 503 normalisation of a PyPI project name."""
    return _PEP503.sub("-", name).lower()
