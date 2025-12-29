
import streamlit as st
import sys, os, importlib.util, subprocess, json
from pathlib import Path

st.set_page_config(page_title="MRTS Bot – Diagnostics", layout="wide")
st.title("MRTS Bot – Environment Diagnostics")

# --- Python / environment info ---
st.subheader("Python & Environment")
st.write({
    "python_version": sys.version.replace("\n", " "),
    "sys_executable": sys.executable,
    "cwd": os.getcwd(),
})
st.caption("sys.path:")
st.code("\n".join(sys.path))

# --- Files present (prove where requirements.txt is) ---
st.subheader("Repo Files (top-level)")
top = Path("/mount/src")
if top.exists():
    st.code("\n".join(sorted(p.name for p in top.iterdir())))
else:
    st.write("`/mount/src` not found")

st.subheader("Files in mrts-bot/")
bot_dir = Path("/mount/src/mrts-bot")
if bot_dir.exists():
    st.code("\n".join(sorted(p.name for p in bot_dir.iterdir())))
else:
    st.write("`/mount/src/mrts-bot` not found")

# --- Does pip see PyMuPDF? ---
st.subheader("pip list (filtered)")
try:
    out = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"],
                         capture_output=True, text=True, check=True)
    pkgs = {p["name"].lower(): p["version"] for p in json.loads(out.stdout)}
    found = {k: v for k, v in pkgs.items() if k in {"pymupdf", "fitz", "streamlit"}}
    st.write(found or "No relevant packages found in pip list")
except Exception as e:
    st.warning(f"pip list failed: {e}")

# --- Can Python resolve modules? ---
st.subheader("importlib.find_spec checks")
pymupdf_spec = importlib.util.find_spec("pymupdf") is not None
fitz_spec = importlib.util.find_spec("fitz") is not None
st.write({"pymupdf_spec": pymupdf_spec, "fitz_spec": fitz_spec})

# --- Try imports safely (no crash) ---
st.subheader("Try importing modules (caught exceptions)")
def try_import(name):
    try:
        mod = __import__(name)
        return {"name": name, "ok": True, "version": getattr(mod, "__version__", "unknown")}
    except Exception as e:
        return {"name": name, "ok": False, "error": str(e)}

st.write(try_import("pymupdf"))
st.write(try_import("fitz"))

st.info("If 'pymupdf_spec'/'fitz_spec' are False and 'pip list' doesn't show PyMuPDF, "
        "Streamlit isn't reading requirements.txt from the correct location.")
