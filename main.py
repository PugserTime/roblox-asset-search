import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from asset_types import asset_type_mapping

# Bot token loaded from an environment variable (recommended over hardcoding)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN environment variable not set.")

# Settings file path
SETTINGS_FILE = Path("settings.json")

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
    return {
        "start_asset_id": 18979790360,
        "creator_ids": [3049798, 16173083, 1776923845, 16009469],
        "search_speed": 1,
        "use_roproxy": True
    }

def save_settings(settings: dict):
    try:
        with SETTINGS_FILE.open("w") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

async def exponential_backoff_request(session: aiohttp.ClientSession, url: str, asset_id: int,
                                        initial_backoff: int = 1, max_backoff: int = 60,
                                        extra_check=None) -> dict:
    backoff = initial_backoff
    while True:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if extra_check and not extra_check(data):
                        print(f"Data not ready for asset {asset_id}.")
                        return None
                    return data
                elif response.status == 429:
                    print(f"Rate limited on asset {asset_id}. Backing off for {backoff} seconds.")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                else:
                    print(f"Unexpected status {response.status} for asset {asset_id} at {url}.")
                    return None
        except Exception as e:
            print(f"Error fetching asset {asset_id} from {url}: {e}")
            await asyncio.sleep(5)
            return None

class AssetScannerBot(commands.Bot):
    def __init__(self, command_prefix: str, intents: discord.Intents):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.settings = load_settings()
        self.start_asset_id = self.settings.get("start_asset_id")
        self.creator_ids = self.settings.get("creator_ids")
        self.search_speed = self.settings.get("search_speed")
        self.use_roproxy = self.settings.get("use_roproxy", False)
        self.client_session: aiohttp.ClientSession = None
        self.searching_task: asyncio.Task = None

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced.")

    async def on_ready(self):
        self.client_session = aiohttp.ClientSession()
        print(f"Logged in as {self.user}")

    async def close(self):
        if self.client_session:
            await self.client_session.close()
        await super().close()

    def update_settings(self):
        self.settings["start_asset_id"] = self.start_asset_id
        self.settings["creator_ids"] = self.creator_ids
        self.settings["search_speed"] = self.search_speed
        self.settings["use_roproxy"] = self.use_roproxy
        save_settings(self.settings)

    async def fetch_asset_thumbnail(self, asset_id: int) -> str:
        url = f"https://thumbnails.roproxy.com/v1/assets?assetIds={asset_id}&size=420x420&format=Png&isCircular=false"
        def check(data):
            if data.get("data") and len(data["data"]) > 0:
                thumbnail = data["data"][0]
                return thumbnail.get("state") == "Completed" and thumbnail.get("imageUrl")
            return False

        data = await exponential_backoff_request(self.client_session, url, asset_id,
                                                 initial_backoff=1, max_backoff=60, extra_check=check)
        if data and data.get("data"):
            return data["data"][0].get("imageUrl")
        return None

    async def fetch_asset_details(self, asset_id: int) -> dict:
        base_url = "https://economy.roproxy.com/v2/assets" if self.use_roproxy else "https://economy.roblox.com/v2/assets"
        url = f"{base_url}/{asset_id}/details"
        return await exponential_backoff_request(self.client_session, url, asset_id, initial_backoff=1, max_backoff=10)

    async def asset_search(self, interaction: Interaction):
        while True:
            try:
                asset_details = await self.fetch_asset_details(self.start_asset_id)
                if asset_details:
                    asset_name = asset_details.get("Name", "Unknown")
                    creator = asset_details.get("Creator", {})
                    creator_id = creator.get("CreatorTargetId", "Unknown")
                    creator_name = creator.get("Name", "Unknown")
                    asset_type_id = asset_details.get("AssetTypeId", "Unknown")
                    asset_type_name = asset_type_mapping.get(asset_type_id, "Unknown")
                    created_date = asset_details.get("Created")

                    # Use the original printed look:
                    print(f"Asset ID: {self.start_asset_id}")
                    print(f"Name: {asset_name}")
                    print(f"Creator Name: {creator_name}")
                    print(f"Creator ID: {creator_id}")
                    print(f"Type: {asset_type_name}, TypeId: {asset_type_id}")
                    print(f"Link: https://create.roblox.com/store/asset/{self.start_asset_id}")
                    print(f"Created: {created_date}")
                    print("-" * 30)

                    # If desired, you can still send embeds when creator is in the list:
                    if creator_id in self.creator_ids:
                        embed = discord.Embed(
                            title=asset_name,
                            color=discord.Color.from_rgb(0, 255, 255)
                        )
                        embed.add_field(
                            name="🗂 Asset",
                            value=(f"ID: ||{self.start_asset_id}||\n"
                                   f"Type: {asset_type_name}\n"
                                   f"[Asset Link](https://create.roblox.com/store/asset/{self.start_asset_id})"),
                            inline=True
                        )
                        embed.add_field(
                            name="👤 Uploader",
                            value=(f"{creator_name}\nType: {creator.get('CreatorType', 'Unknown')}\nID: {creator_id}"),
                            inline=True
                        )
                        if created_date:
                            try:
                                created_date_obj = datetime.strptime(created_date, "%Y-%m-%dT%H:%M:%S.%fZ")
                            except ValueError:
                                created_date_obj = datetime.strptime(created_date, "%Y-%m-%dT%H:%M:%SZ")
                            created_timestamp = int(created_date_obj.timestamp())
                            embed.add_field(name="📅 Created", value=f"<t:{created_timestamp}:f>", inline=False)
                        thumbnail_url = await self.fetch_asset_thumbnail(self.start_asset_id)
                        if thumbnail_url:
                            embed.set_thumbnail(url=thumbnail_url)
                        embed.set_footer(
                            text="LeakHub [LeakHub Scanner]",
                            icon_url=(self.user.avatar.url if self.user.avatar else self.user.default_avatar.url)
                        )
                        await interaction.channel.send(embed=embed)

                self.start_asset_id += 1
                self.update_settings()
                await asyncio.sleep(self.search_speed)
            except asyncio.CancelledError:
                print("Asset search cancelled.")
                break
            except Exception as e:
                print(f"Error during asset search: {e}")

# Instantiate bot with default intents
intents = discord.Intents.default()
bot = AssetScannerBot(command_prefix="!", intents=intents)

# Slash commands

@bot.tree.command(name="start_search", description="Start searching for assets.")
async def start_search(interaction: Interaction):
    if bot.searching_task and not bot.searching_task.done():
        await interaction.response.send_message("Search is already running!", ephemeral=True)
        return
    bot.searching_task = asyncio.create_task(bot.asset_search(interaction))
    await interaction.response.send_message("Started searching for assets!", ephemeral=True)

@bot.tree.command(name="stop_search", description="Stop the asset search.")
async def stop_search(interaction: Interaction):
    if bot.searching_task and not bot.searching_task.done():
        bot.searching_task.cancel()
        await interaction.response.send_message("Stopped the search.", ephemeral=True)
    else:
        await interaction.response.send_message("No search is currently running.", ephemeral=True)

@bot.tree.command(name="view_settings", description="View current search settings.")
async def view_settings(interaction: Interaction):
    settings_message = (
        "**Current Search Settings:**\n"
        f"**Start Asset ID:** {bot.start_asset_id}\n"
        f"**Search Speed:** {bot.search_speed} seconds\n"
        f"**Creator IDs:** {', '.join(map(str, bot.creator_ids))}\n"
        f"**Use RoProxy:** {'Enabled' if bot.use_roproxy else 'Disabled'}\n"
    )
    await interaction.response.send_message(settings_message, ephemeral=True)

@bot.tree.command(name="set_start_asset", description="Set the starting asset ID for the search.")
async def set_start_asset(interaction: Interaction, asset_id: int):
    bot.start_asset_id = asset_id
    bot.update_settings()
    await interaction.response.send_message(f"Start asset ID set to {bot.start_asset_id}.", ephemeral=True)

@bot.tree.command(name="add_creators", description="Add multiple creator IDs to the search list.")
async def add_creators(interaction: Interaction, new_creator_ids: str):
    new_ids = [int(cid.strip()) for cid in new_creator_ids.split(",") if cid.strip().isdigit()]
    added_ids = []
    for cid in new_ids:
        if cid not in bot.creator_ids:
            bot.creator_ids.append(cid)
            added_ids.append(cid)
    bot.update_settings()
    if added_ids:
        await interaction.response.send_message(f"Added creator IDs: {', '.join(map(str, added_ids))}", ephemeral=True)
    else:
        await interaction.response.send_message("No new creator IDs were added.", ephemeral=True)

@bot.tree.command(name="remove_creator", description="Remove a creator ID from the search list.")
async def remove_creator(interaction: Interaction, creator_id: int):
    if creator_id in bot.creator_ids:
        bot.creator_ids.remove(creator_id)
        bot.update_settings()
        await interaction.response.send_message(f"Removed creator ID {creator_id}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Creator ID {creator_id} not found.", ephemeral=True)

@bot.tree.command(name="toggle_roproxy", description="Toggle using RoProxy for asset detail requests.")
async def toggle_roproxy(interaction: Interaction):
    bot.use_roproxy = not bot.use_roproxy
    bot.update_settings()
    status = "enabled" if bot.use_roproxy else "disabled"
    await interaction.response.send_message(f"RoProxy has been {status}.", ephemeral=True)

@bot.tree.command(name="set_speed", description="Set the search speed in seconds.")
async def set_speed(interaction: Interaction, speed: float):
    bot.search_speed = speed
    bot.update_settings()
    await interaction.response.send_message(f"Search speed updated to {bot.search_speed} seconds.", ephemeral=True)

bot.run(TOKEN)
