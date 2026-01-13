from fastapi import FastAPI, HTTPException
import logging
import uvicorn

logger = logging.getLogger(__name__)
app = FastAPI()

def main():
    """
    Entry point for the Process Watcher application.
    Starts the Uvicorn server with the FastAPI app.
    """
    # The monitor thread is already started when importing 'app' from 'api'
    # because of the module-level code in api.py.
    uvicorn.run(app, host="127.0.0.1", port=7102)

if __name__ == "__main__":
    main()