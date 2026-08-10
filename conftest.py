import os
import sys

# Rendre le projet importable depuis n'importe où
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# DB de test isolée (ne jamais toucher la DB de prod)
_TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "test.db")
os.environ.setdefault("MINIHEROKU_DB", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("MINIHEROKU_FERNET_KEY_FILE",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "tests", "test-fernet.key"))
os.environ.setdefault("MINIHEROKU_CADDYFILE",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "tests", "test-Caddyfile"))
os.environ.setdefault("MINIHEROKU_CADDY_RELOAD", "0")
