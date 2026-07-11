from pathlib import Path

from openline_endurance_gate.experiment import run_experiment

if __name__ == "__main__":
    print(run_experiment(Path(__file__).resolve().parents[1]))
