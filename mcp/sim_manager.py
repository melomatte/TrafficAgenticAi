import traci, socket, time

class SimManager:
    def __init__(self, host: str, port: int = 8813):
        self.host = host
        self.port = port

    def start(self):
        print(f"Waiting for SUMO TraCI server at {self.host}:{self.port}...")
        self._wait_for_port(timeout=120)        # increased timeout
        
        print("Connecting to TraCI...")
        max_retries = 10
        for attempt in range(max_retries):
            try:
                traci.connect(host=self.host, port=self.port)
                print("Successfully connected to SUMO via TraCI")
                return
            except Exception as e:
                print(f"Attempt {attempt+1}/{max_retries} failed: {e}")
                time.sleep(5)
        
        raise RuntimeError("Failed to connect to TraCI after multiple attempts")


    def stop(self):
        traci.close()

    def _wait_for_port(self, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection((self.host, self.port), timeout=1):
                    return
            except OSError:
                time.sleep(3)
        raise RuntimeError(f"SUMO at {self.host}:{self.port} not reachable after {timeout}s")