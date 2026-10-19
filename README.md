# Lista

Aplicación web sencilla para que cada usuario organice sus propias tareas.

## Requisitos

- Python 3.10 o posterior
- Flask

## Ejecutar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "cambia-esto-por-una-clave-aleatoria"
python app.py
```

Abre http://127.0.0.1:5000. La base de datos SQLite se crea automáticamente en `instance/tasks.sqlite3`.
En desarrollo se puede activar el modo de depuración con `$env:FLASK_DEBUG = "1"`.

## Pruebas

```powershell
python -m unittest discover -s tests
```
# Demo-Vibe
