import argparse
import asyncio
import logging
import sys
import uvicorn
from bot import main as start_bot
from config import settings
from main import app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Gym16_Runner")

async def run_api():
    port = int(os.getenv("PORT", settings.PORT))
    config = uvicorn.Config(
        app=app,
        host=settings.HOST,
        port=port,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_both():
    logger.info("Starting both FastAPI API and aiogram 3 Bot concurrently...")
    await asyncio.gather(
        run_api(),
        start_bot()
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gymnasium 16 TMA Runner")
    parser.add_argument("--api-only", action="store_true", help="Run only FastAPI backend")
    parser.add_argument("--bot-only", action="store_true", help="Run only Telegram Bot")
    args = parser.parse_args()

    try:
        if args.api_only:
            asyncio.run(run_api())
        elif args.bot_only:
            asyncio.run(start_bot())
        else:
            asyncio.run(run_both())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Service stopped gracefully.")
