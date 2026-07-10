import sys
import os

# main.py uses bare imports like `from model.load import load_model`, so the
# agent root must be on sys.path when pytest collects tests here.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
