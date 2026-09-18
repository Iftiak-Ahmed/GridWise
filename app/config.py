"""Environment-driven configuration. No secret values ever hard-coded here."""
import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))
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
