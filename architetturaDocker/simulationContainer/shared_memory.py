class SharedState:
    """Classe per gestire lo stato condiviso tra SUMO e FastAPI in modo sicuro."""
    def __init__(self):
        self.simulation_state = {}       # Lavagna per lo Stress Index
        self.static_lane_lengths = {}    # Lunghezze delle strade
        self.pending_commands = []       # Comandi in arrivo dall'agente

# Creiamo l'istanza globale (Singleton) che useremo ovunque
state = SharedState()