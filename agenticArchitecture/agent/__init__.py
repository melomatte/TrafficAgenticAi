# Importiamo la classe principale del nostro agente da config.py
from .config import TrafficAgent

# (Opzionale) Definiamo cosa viene esportato se qualcuno fa "from agent import *"
__all__ = ["TrafficAgent"]