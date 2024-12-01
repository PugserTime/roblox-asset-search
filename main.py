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

# Load settings from a file
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {
            "start_asset_id": 18979790360,
            "creator_ids": [3049798, 16173083, 1776923845, 16009469],
            "search_speed": 1
        }

# Save settings to a file
def save_settings():
    global start_asset_id, creator_ids, search_speed
    settings = {
        "start_asset_id": start_asset_id,
        "creator_ids": creator_ids,
        "search_speed": search_speed
    }
    with open(SETTINGS_FILE, 'w') as file:
        json.dump(settings, file)

# Initialize settings
settings = load_settings()
start_asset_id = settings["start_asset_id"]
creator_ids = settings["creator_ids"]
search_speed = settings["search_speed"]

# Bot setup
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

RATE_LIMIT_COOLDOWN = 60
last_rate_limit_time = None
searching_task = None
cache = {}

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'Logged in as {bot.user}')
    print("Slash commands synced.")

# Fetch asset thumbnail
async def fetch_asset_thumbnail(asset_id):
    url = f"https://rbxgleaks.pythonanywhere.com/asset/v2/{asset_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return str(response.url)
            else:
                print(f"Failed to fetch asset thumbnail for ID {asset_id}. Status: {response.status}")
                return None

# Commands
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
    await interaction.response.send_message(settings_message, ephemeral=True)

@bot.tree.command(name="set_start_asset", description="Set the starting asset ID for the search.")
async def set_start_asset(interaction: Interaction, asset_id: int):
    global start_asset_id
    start_asset_id = asset_id
    save_settings()
    await interaction.response.send_message(f"Start asset ID set to {start_asset_id}.", ephemeral=True)

@bot.tree.command(name="add_creators", description="Add multiple creator IDs to the search list.")
async def add_creators(interaction: Interaction, new_creator_ids: str):
    """
    Add multiple creator IDs to the search list.
    :param interaction: The interaction object from the command.
    :param new_creator_ids: A comma-separated string of creator IDs.
    """
    global creator_ids

    # Parse and clean input
    new_ids = [int(creator_id.strip()) for creator_id in new_creator_ids.split(",") if creator_id.strip().isdigit()]
    added_ids = []

    for creator_id in new_ids:
        if creator_id not in creator_ids:
            creator_ids.append(creator_id)
            added_ids.append(creator_id)

    save_settings()

    if added_ids:
        await interaction.response.send_message(
            f"Added the following creator IDs to the search list: {', '.join(map(str, added_ids))}", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "No new creator IDs were added. They may already be in the search list.", ephemeral=True
        )


@bot.tree.command(name="remove_creator", description="Remove a creator ID from the search list.")
async def remove_creator(interaction: Interaction, creator_id: int):
    global creator_ids
    if creator_id in creator_ids:
        creator_ids.remove(creator_id)
        save_settings()
        await interaction.response.send_message(f"Removed creator ID {creator_id} from the search list.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Creator ID {creator_id} not found in the search list.", ephemeral=True)

async def fetch_asset_details(asset_id):
    global last_rate_limit_time

    if asset_id in cache:
        return cache[asset_id]

    if last_rate_limit_time and datetime.now() < last_rate_limit_time + timedelta(seconds=RATE_LIMIT_COOLDOWN):
        cooldown = (last_rate_limit_time + timedelta(seconds=RATE_LIMIT_COOLDOWN) - datetime.now()).seconds
        await asyncio.sleep(cooldown)

    url = f"https://economy.roblox.com/v2/assets/{asset_id}/details"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    print(f"Fetching asset {asset_id}, Status: {response.status}")  # Log the status
                    if response.status == 200:
                        data = await response.json()
                        cache[asset_id] = data
                        return data
                    elif response.status == 400:
                        print(f"Asset {asset_id} not found (400).")
                        return None
                    elif response.status == 429:
                        last_rate_limit_time = datetime.now()
                        print("Rate limit exceeded (429). Retrying after cooldown.")
                        await asyncio.sleep(RATE_LIMIT_COOLDOWN)
                    else:
                        print(f"Unexpected status {response.status} for asset {asset_id}. Retrying.")
                        return None
        except Exception as e:
            await asyncio.sleep(5)

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

                # Safely parse the Created date
                if created_date:
                    try:
                        created_date_obj = datetime.strptime(created_date, "%Y-%m-%dT%H:%M:%S.%fZ")
                    except ValueError:
                        created_date_obj = datetime.strptime(created_date, "%Y-%m-%dT%H:%M:%SZ")
                    
                    # Convert to Unix timestamp
                    created_timestamp = int(created_date_obj.timestamp())
                else:
                    created_date_obj = None
                    created_timestamp = None

                # Debug output
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
                    embed.add_field(name="🗂 Asset", value=f"ID: ||{start_asset_id}||\nType: {asset_type_name}\n[Asset Link](https://create.roblox.com/store/asset/{start_asset_id})", inline=True)
                    embed.add_field(name="👤 Uploader", value=f"{creator_name}\nType: {creator_type}\nID: {creator_id}", inline=True)

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
            # Gracefully handle task cancellation
            break

        except Exception as e:
            # Log unexpected errors for debugging
            print(f"Error occurred during asset search: {e}")

bot.run(TOKEN)
