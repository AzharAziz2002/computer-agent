import uvicorn
from medusa.api.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)


# To start:
#   cd computer
#   uv add fastapi[standard] uvicorn[standard]   # install new deps
#   python server.py                              # starts on http://127.0.0.1:8000

#   Then start the frontend with npm run dev — submitting a task will POST to /api/tasks, and step updates will stream
#   over WebSocket to the UI.