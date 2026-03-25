import logging

from alert_ai.app import create_app

logging.basicConfig(level=logging.INFO)

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
