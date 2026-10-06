# Jiji — logiciel de calcul de moyennes scolaires

Application complète pour gérer les **filières, classes, matières, élèves, évaluations et notes**, et produire
automatiquement **moyennes, rangs, mentions, statistiques de classe et bulletins** imprimables.

- 100 % local : une base SQLite (`jiji.db`), aucune connexion Internet requise
- **Aucune dépendance** : Python 3.11+ uniquement (bibliothèque standard)
- Interface web en français (s'ouvre dans votre navigateur)

## Démarrage

```bash
python3 -m jiji            # ou ./lancer.sh  /  double-clic sur « Lancer Jiji.bat » (Windows)
# ou, avec le fichier unique : python3 jiji.pyz   (construit par ./build.sh)
```

Le navigateur s'ouvre sur http://localhost:8765. Au premier lancement, créez le compte administrateur.

Options : `--db fichier.db`, `--port 8765`, `--host 0.0.0.0` (partage sur le réseau local), `--no-browser`.

Pour tester avec des données fictives : `python3 -m jiji.demo demo.db && python3 -m jiji --db demo.db` (compte `admin` / `demo123`).

## Fonctionnalités

| Domaine | Détail |
|---|---|
| Organisation | Années scolaires, périodes (trimestres/semestres en un clic) avec poids, filières, matières |
| Classes | Rattachées à une filière ; matières affectées avec **coefficient** et enseignant ; copie des matières d'une autre classe |
| Élèves | Fiche complète, recherche, **import CSV** (séparateur auto, dates `JJ/MM/AAAA`, mise à jour par matricule) |
| Notes | Évaluations (devoir, composition…) avec **barème** et **poids** propres ; grille de saisie rapide (Entrée, Ctrl+S), absences |
| Résultats | Moyennes par matière, moyenne générale, **rang** (ex æquo gérés), mention, moyenne/min/max de classe, taux de réussite, export CSV compatible Excel |
| Annuel | Moyenne annuelle pondérée par le poids des périodes |
| Bulletins | Bulletin A4 par élève ou pour toute la classe → impression / PDF |
| Paramètres | Barème, moyenne de passage, mentions personnalisables, mot de passe, **sauvegarde** de la base |

## Règles de calcul

1. Note ramenée au barème de l'établissement (20 par défaut) : `note / barème_éval × 20`.
2. Moyenne de matière = moyenne des évaluations **pondérée par leur poids**.
3. Moyenne générale = `Σ(moyenne matière × coefficient) / Σ coefficients` sur les matières notées.
4. Un élève **absent** ou sans note n'est pas pénalisé : l'évaluation est ignorée pour lui.
5. Moyenne annuelle = moyenne des moyennes de période pondérée par le poids de chaque période.
6. Rang « sportif » (1, 1, 3…) sur les moyennes arrondies à 2 décimales.

## Sécurité

Authentification par mot de passe (PBKDF2), session en cookie `HttpOnly`/`SameSite=Strict`, protection CSRF par
en-tête, limitation des tentatives de connexion, contrôle de l'en-tête `Host` en mode local, requêtes SQL paramétrées,
échappement systématique côté interface. Par défaut le serveur n'écoute que sur `127.0.0.1`. Si vous l'exposez sur un
réseau (`--host 0.0.0.0`), placez-le derrière HTTPS (reverse proxy).

## Tests

```bash
python3 -m unittest discover tests
```

## Structure

```
jiji/calc.py     moteur de calcul (moyennes, rangs, mentions)
jiji/api.py      validation, CRUD, import CSV, notes, rapports
jiji/server.py   serveur HTTP + authentification
jiji/db.py       schéma SQLite
jiji/static/     interface web (HTML/CSS/JS)
tests/           tests unitaires et d'intégration
```
