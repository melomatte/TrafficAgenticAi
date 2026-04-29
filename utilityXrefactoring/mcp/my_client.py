import asyncio
from fastmcp import Client

client = Client("https://localhost:8000")

async def call_tool(name: str):
    async with client:
        result = await client.call_tool(name)
        print(result)

