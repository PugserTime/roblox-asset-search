import discord
from discord.ext import commands
from discord import app_commands, Interaction
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta
from asset_types import asset_type_mapping

# Bot token
TOKEN = 'token here'  # Replace with your bot token

# Settings file
SETTINGS_FILE = 'settings.json'

# Global aiohttp session for reuse
client_session = None

# Load settings from a file
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {
            "start_asset_id": 18979790360,
            "creator_ids": [3049798, 16173083, 1776923845, 16009469],
            "search_speed": 1,
            "use_roproxy": False  # Default: do not use RoProxy
        }

# Save settings to a file
def save_settings():
    global start_asset_id, creator_ids, search_speed, use_roproxy
    settings = {
        "start_asset_id": start_asset_id,
        "creator_ids": creator_ids,
        "search_speed": search_speed,
        "use_roproxy": use_roproxy
    }
    with open(SETTINGS_FILE, 'w') as file:
        json.dump(settings, file)

# Initialize settings
settings = load_settings()
start_asset_id = settings["start_asset_id"]
creator_ids = settings["creator_ids"]
search_speed = settings["search_speed"]
use_roproxy = settings.get("use_roproxy", False)

# Bot setup
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variable for search task
searching_task = None

@bot.event
async def on_ready():
    global client_session
    client_session = aiohttp.ClientSession()  # Create one global session
    await bot.tree.sync()
    print(f'Logged in as {bot.user}')
    print("Slash commands synced.")

@bot.event
async def on_close():
    global client_session
    if client_session:
        await client_session.close()

# Fetch asset thumbnail that returns the image URL from the API response.
# Implements exponential backoff on rate limits.
async def fetch_asset_thumbnail(asset_id):
    url = f"https://thumbnails.roproxy.com/v1/assets?assetIds={asset_id}&size=420x420&format=Png&isCircular=false"
    backoff = 1
    while True:
        try:
            async with client_session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('data') and len(data['data']) > 0:
                        thumbnail_data = data['data'][0]
                        if thumbnail_data.get('state') == 'Completed' and thumbnail_data.get('imageUrl'):
                            return thumbnail_data['imageUrl']
                        else:
                            print(f"Thumbnail not ready or missing for asset ID {asset_id}.")
                            return None
                    else:
                        print(f"No thumbnail data found for asset ID {asset_id}.")
                        return None
                elif response.status == 429:
                    print(f"Thumbnail rate limit hit for asset {asset_id}. Backing off for {backoff} seconds.")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                else:
                    print(f"Failed to fetch asset thumbnail for ID {asset_id}. Status: {response.status}")
                    return None
        except Exception as e:
            print(f"Error in fetch_asset_thumbnail for asset {asset_id}: {e}")
            await asyncio.sleep(5)
            return None

# Fetch asset details with exponential backoff on rate limits.
async def fetch_asset_details(asset_id):
    # Toggle URL based on the use_roproxy setting.
    if use_roproxy:
        url = f"https://economy.roproxy.com/v2/assets/{asset_id}/details"
    else:
        url = f"https://economy.roblox.com/v2/assets/{asset_id}/details"

    backoff = 1
    while True:
        try:
            async with client_session.get(url) as response:
                print(f"Fetching asset {asset_id}, Status: {response.status}")
                if response.status == 200:
                    return await response.json()
                elif response.status == 400:
                    print(f"Asset {asset_id} not found (400).")
                    return None
                elif response.status == 429:
                    print(f"Asset details rate limit hit for asset {asset_id}. Backing off for {backoff} seconds.")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 10)
                    continue
                else:
                    print(f"Unexpected status {response.status} for asset {asset_id}.")
                    return None
        except Exception as e:
            print(f"Error fetching asset {asset_id}: {e}")
            await asyncio.sleep(5)

# Asset search loop with additional optimization and error handling.
async def asset_search(interaction: Interaction):
    global start_asset_id, search_speed
    while True:
        try:
            asset_details = await fetch_asset_details(start_asset_id)
            if asset_details:
                asset_name = asset_details.get("Name", "Unknown")
                creator_id = asset_details.get("Creator", {}).get("CreatorTargetId", "Unknown")
                creator_type = asset_details.get("Creator", {}).get("CreatorType", "Unknown")
                creator_name = asset_details.get("Creator", {}).get("Name", "Unknown")
                asset_type_id = asset_details.get("AssetTypeId", "Unknown")
                asset_type_name = asset_type_mapping.get(asset_type_id, "Unknown")
                created_date = asset_details.get("Created", None)

                if created_date:
                    try:
                        created_date_obj = datetime.strptime(created_date, "%Y-%m-%dT%H:%M:%S.%fZ")
                    except ValueError:
                        created_date_obj = datetime.strptime(created_date, "%Y-%m-%dT%H:%M:%SZ")
                    created_timestamp = int(created_date_obj.timestamp())
                else:
                    created_timestamp = None

                print(f"Asset ID: {start_asset_id}")
                print(f"Name: {asset_name}")
                print(f"Creator Name: {creator_name}")
                print(f"Creator ID: {creator_id}")
                print(f"Type: {asset_type_name}")
                print(f"Created: {created_date}")
                print("-" * 30)

                if creator_id in creator_ids:
                    embed = discord.Embed(
                        title=asset_name,
                        color=discord.Color.from_rgb(0, 255, 255)
                    )
                    embed.add_field(
                        name="🗂 Asset", 
                        value=f"ID: ||{start_asset_id}||\nType: {asset_type_name}\n[Asset Link](https://create.roblox.com/store/asset/{start_asset_id})", 
                        inline=True
                    )
                    embed.add_field(
                        name="👤 Uploader", 
                        value=f"{creator_name}\nType: {creator_type}\nID: {creator_id}", 
                        inline=True
                    )
                    if created_timestamp:
                        embed.add_field(name="📅 Created", value=f"<t:{created_timestamp}:f>", inline=False)

                    thumbnail_url = await fetch_asset_thumbnail(start_asset_id)
                    if thumbnail_url:
                        embed.set_thumbnail(url=thumbnail_url)

                    embed.set_footer(
                        text="LeakHub [LeakHub Scanner]",
                        icon_url=(bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url)
                    )
                    await interaction.channel.send(embed=embed)

            start_asset_id += 1
            save_settings()
            await asyncio.sleep(search_speed)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error occurred during asset search: {e}")

# Slash Commands

@bot.tree.command(name="start_search", description="Start searching for assets.")
async def start_search(interaction: Interaction):
    global searching_task
    if searching_task and not searching_task.done():
        await interaction.response.send_message("Search is already running!", ephemeral=True)
        return
    searching_task = asyncio.create_task(asset_search(interaction))
    await interaction.response.send_message("Started searching for assets!", ephemeral=True)

@bot.tree.command(name="stop_search", description="Stop the asset search.")
async def stop_search(interaction: Interaction):
    global searching_task
    if searching_task and not searching_task.done():
        searching_task.cancel()
        await interaction.response.send_message("Stopped the search.", ephemeral=True)
    else:
        await interaction.response.send_message("No search is currently running.", ephemeral=True)

@bot.tree.command(name="view_settings", description="View current search settings.")
async def view_settings(interaction: Interaction):
    settings_message = "**Current Search Settings:**\n"
    settings_message += f"**Start Asset ID:** {start_asset_id}\n"
    settings_message += f"**Search Speed:** {search_speed} seconds\n"
    settings_message += f"**Creator IDs:** {', '.join(map(str, creator_ids))}\n"
    settings_message += f"**Use RoProxy:** {'Enabled' if use_roproxy else 'Disabled'}\n"
    await interaction.response.send_message(settings_message, ephemeral=True)

@bot.tree.command(name="set_start_asset", description="Set the starting asset ID for the search.")
async def set_start_asset(interaction: Interaction, asset_id: int):
    global start_asset_id
    start_asset_id = asset_id
    save_settings()
    await interaction.response.send_message(f"Start asset ID set to {start_asset_id}.", ephemeral=True)

@bot.tree.command(name="add_creators", description="Add multiple creator IDs to the search list.")
async def add_creators(interaction: Interaction, new_creator_ids: str):
    global creator_ids
    new_ids = [int(cid.strip()) for cid in new_creator_ids.split(",") if cid.strip().isdigit()]
    added_ids = []
    for cid in new_ids:
        if cid not in creator_ids:
            creator_ids.append(cid)
            added_ids.append(cid)
    save_settings()
    if added_ids:
        await interaction.response.send_message(f"Added creator IDs: {', '.join(map(str, added_ids))}", ephemeral=True)
    else:
        await interaction.response.send_message("No new creator IDs were added.", ephemeral=True)

@bot.tree.command(name="remove_creator", description="Remove a creator ID from the search list.")
async def remove_creator(interaction: Interaction, creator_id: int):
    global creator_ids
    if creator_id in creator_ids:
        creator_ids.remove(creator_id)
        save_settings()
        await interaction.response.send_message(f"Removed creator ID {creator_id}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Creator ID {creator_id} not found.", ephemeral=True)

@bot.tree.command(name="toggle_roproxy", description="Toggle using RoProxy for asset detail requests.")
async def toggle_roproxy(interaction: Interaction):
    global use_roproxy
    use_roproxy = not use_roproxy
    save_settings()
    status = "enabled" if use_roproxy else "disabled"
    await interaction.response.send_message(f"RoProxy has been {status}.", ephemeral=True)

@bot.tree.command(name="set_speed", description="Set the search speed in seconds.")
async def set_speed(interaction: Interaction, speed: float):
    global search_speed
    search_speed = speed
    save_settings()
    await interaction.response.send_message(f"Search speed updated to {search_speed} seconds.", ephemeral=True)

bot.run(TOKEN)
