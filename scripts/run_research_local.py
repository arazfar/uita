"""Local-only research server with non-secure cookies; hosted factory remains secure."""

import uvicorn
from uita.research.api import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(secure_cookies=False), host="127.0.0.1", port=8012)
