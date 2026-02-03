"""
Backend subtool: populate the global AI instruction from message data.

Uses seller messages from up to 100 threads (and draft feedback) to generate
a single global instruction and writes it to the global AIInstruction.
Seller = sender_type 'seller' or sender_username EBAY_SELLER_USERNAME or "evamp_".

Run from backend directory:
  python scripts/populate_global_instruction.py

Or via Docker:
  docker compose exec backend python scripts/populate_global_instruction.py
"""
import asyncio
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.core.database import async_session_maker
from app.services.global_instruction_from_history import generate_global_instruction_from_history


async def run() -> None:
    async with async_session_maker() as db:
        out = await generate_global_instruction_from_history(db)
        if out["success"]:
            print(out["message"])
            print("Done. Global instruction length:", len(out["instructions"] or ""), "chars.")
        else:
            print(out["message"])


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
