import traci

sumoCmd = [
    "/Users/raffaele/sumo/bin/sumo-gui",
    "-c",
    "/Users/raffaele/PycharmProjects/TrafficAgenticAi/Simulazione Sumo/Prova_VialeAldini/osm.sumocfg",
    "--start",
    "--delay", "100"
]

traci.start(sumoCmd)

tls_ids = traci.trafficlight.getIDList()
print("Semafori:", tls_ids)

for step in range(500):
    traci.simulationStep()

    for tls_id in tls_ids:
        stato = traci.trafficlight.getRedYellowGreenState(tls_id)
        rosso_fisso = "r" * len(stato)
        traci.trafficlight.setRedYellowGreenState(tls_id, rosso_fisso)

        if step == 0:
            print(tls_id, "=>", stato, "->", rosso_fisso)

traci.close()