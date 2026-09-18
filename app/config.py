"""Environment-driven configuration. No secret values ever hard-coded here."""
import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Groq (LPU inference) is typically sub-2s; Gemini flash-lite is typically 5-15s. Separate
# per-provider budgets so a slow-but-alive Gemini call isn't cut off too early while the
# combined worst case (both attempted) still lands safely under the 30s judge timeout.
GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "6"))
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "18"))
PORT = int(os.getenv("PORT", "8000"))

# Directive types supported by the challenge (Problem Statement Sec. 04.1).
DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

# Absolute numeric tolerance used internally for rounding / comparisons (Sec. 11.5).
NUMERIC_TOLERANCE = 0.01
