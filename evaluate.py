"""Évaluation honnête de l'agent : on lui cache FINESS et on regarde s'il retrouve la vérité.

Vérité terrain (établie SANS l'agent, par le filtre 1 + FINESS) :
  - 33 associations/fondations confirmées médico-sociales par FINESS (règle R20, confiance « sur »)
  - 7 bailleurs sociaux certains par leur forme juridique (règle R04), tirés au hasard (graine fixe),
    comme groupe témoin : l'agent doit les distinguer des médico-sociaux, pas tout classer médico-social.
L'agent tourne SANS l'outil FINESS et sans voir la famille attendue (il ne reçoit que nom et forme juridique).

Limites à écrire dans la note : 40 cas seulement ; la vérité terrain ne couvre que des demandeurs
présents dans FINESS (ou à forme juridique explicite) ; aucun cas « négatif » difficile (SCI, promoteur).

Usage :
  python evaluate.py              # lance l'agent (s'il reste des cas) puis calcule les scores
  python evaluate.py --score-only
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

DATA = Path("data/processed")
TAG = "_eval"
RESULTS = DATA / f"agent_results{TAG}.jsonl"
N_TEMOINS = 7


def verite() -> pd.DataFrame:
    d = pd.read_csv(DATA / "demandeurs_f2.csv", dtype=str)
    pos = d[(d["regle"] == "R20") & (d["confiance"] == "sur")].assign(attendu="medico_social")
    tem = d[d["regle"] == "R04"].sample(n=N_TEMOINS, random_state=0).assign(attendu="bailleur_social")
    return pd.concat([pos, tem])[["siren", "denomination", "cj", "attendu"]].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-only", action="store_true")
    a = ap.parse_args()
    gt = verite()
    print(f"Vérité terrain : {len(gt)} demandeurs ({(gt.attendu == 'medico_social').sum()} médico-sociaux, "
          f"{(gt.attendu == 'bailleur_social').sum()} bailleurs sociaux témoins)")
    if not a.score_only:
        subprocess.run(
            [sys.executable, "-X", "utf8", "filter3.py", "--sans-finess", "--tag", TAG, "--siren", *gt["siren"]],
            check=True,
        )
    if not RESULTS.exists():
        sys.exit("Aucun résultat à scorer.")
    res = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        res[r["siren"]] = r
    gt = gt[gt["siren"].isin(res)].copy()
    gt["agent"] = [res[s]["decision"]["famille"] for s in gt["siren"]]
    gt["confiance"] = [res[s]["decision"]["confiance"] for s in gt["siren"]]
    gt["garde_fou"] = [res[s]["decision"]["garde_fou"] for s in gt["siren"]]
    gt["outils"] = [",".join(a["outil"] for a in res[s]["appels"]) for s in gt["siren"]]
    gt["ok"] = gt["agent"] == gt["attendu"]
    gt.to_csv(DATA / "evaluation_sans_finess.csv", index=False)

    print(f"\nCas évalués : {len(gt)}")
    for att, g in gt.groupby("attendu"):
        print(f"\n== Attendu : {att} ({len(g)} cas)")
        print(f"   Bonne famille : {g['ok'].sum()} / {len(g)} ({g['ok'].mean():.0%})")
        print("   Réponses de l'agent :")
        print(g["agent"].value_counts().to_string().replace("\n", "\n     "))
    print("\nTous les cas ratés ou « non_determine » :")
    print(gt[~gt["ok"]][["denomination", "attendu", "agent", "confiance"]].to_string(index=False))
    tok = sum(r["tokens"] for r in res.values() if r["siren"] in set(gt["siren"]))
    print(f"\nTokens utilisés : {tok}  |  gardes-fous déclenchés : {(gt['garde_fou'] != 'ok').sum()}")


if __name__ == "__main__":
    main()
