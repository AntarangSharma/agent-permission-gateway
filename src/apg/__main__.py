import uvicorn
from dotenv import load_dotenv

from apg.web import create_app


def main() -> None:
    load_dotenv()
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
