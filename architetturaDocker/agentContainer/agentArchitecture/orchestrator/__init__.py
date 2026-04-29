# Importiamo la classe principale del nostro agente da config.py
from .orchestrator_core import Orchestrator

# (Opzionale) Definiamo cosa viene esportato se qualcuno fa "from agent import *"
__all__ = ["Orchestrator"]