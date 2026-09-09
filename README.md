# Notebook venv — kurze Schritte

1. Erstelle ein virtuelles Umfeld:

```
python3 -m venv .venv
```

2. Aktiviere es (zsh/macOS):

```
source .venv/bin/activate
```

3. Pip updaten und Abhängigkeiten installieren:

```
pip install --upgrade pip
pip install -r requirements.txt
```

4. IPython-Kernel für das Projekt registrieren:

```
python -m ipykernel install --user --name=streamlit-demo --display-name="Python (streamlit-demo)"
```

5. Notebook starten (optional):

```

Streamlit starten
---------------

Lege eine lokale Datei `.streamlit/secrets.toml` an und trage dort deinen Key ein:

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-4o-mini"
```

Alternativ kannst du den Key lokal auch als Umgebungsvariable setzen:

```bash
export OPENAI_API_KEY="sk-..."
```

Dann starte die App mit:

```bash
streamlit run app.py
```

Hinweis: `requirements.txt` wurde erweitert um `streamlit` und `pydantic`.

Fertig — öffne das Notebook und wähle den Kernel "Python (streamlit-demo)".