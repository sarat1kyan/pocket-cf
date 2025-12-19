#!/usr/bin/env python3
"""
Cloudflare Telegram Bot - Interactive Installation Script
Provides a beautiful UI to collect all necessary configuration.
"""

import os
import sys
import re
import json
from typing import Optional, List
from pathlib import Path

# Check if rich is available, fallback to basic input if not
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich.table import Table
    from rich import box
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Warning: 'rich' library not found. Installing basic version...")
    print("For a better experience, install: pip install rich")
    print()

# Fallback console if rich is not available
if not RICH_AVAILABLE:
    class Console:
        def print(self, *args, **kwargs):
            print(*args)
        def rule(self, *args, **kwargs):
            print("=" * 60)
    
    class Panel:
        def __init__(self, content, **kwargs):
            self.content = content
        def __str__(self):
            return str(self.content)
    
    class Prompt:
        @staticmethod
        def ask(prompt: str, default: Optional[str] = None, password: bool = False) -> str:
            prefix = prompt.strip()
            if default:
                prefix += f" [{default}]"
            prefix += ": "
            if password:
                import getpass
                result = getpass.getpass(prefix)
                return result if result else (default or "")
            result = input(prefix)
            return result if result else (default or "")
    
    class Confirm:
        @staticmethod
        def ask(question: str, default: bool = True) -> bool:
            yn = "Y/n" if default else "y/N"
            resp = input(f"{question} [{yn}]: ").strip().lower()
            if not resp:
                return default
            return resp in ('y', 'yes')

console = Console()

# Color codes for basic terminal (fallback)
class Colors:
    HEADER = '\033[95m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    BLUE = '\033[94m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    CYAN = '\033[96m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    GREEN = '\033[92m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    YELLOW = '\033[93m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    RED = '\033[91m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    END = '\033[0m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    BOLD = '\033[1m' if sys.platform != 'win32' or os.getenv('TERM') else ''
    UNDERLINE = '\033[4m' if sys.platform != 'win32' or os.getenv('TERM') else ''


def print_header():
    """Print the welcome header."""
    header = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║     🤖 Cloudflare Telegram Bot - Installation Wizard        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    if RICH_AVAILABLE:
        console.print(Panel(header.strip(), border_style="cyan", padding=(1, 2)))
    else:
        print(Colors.CYAN + header + Colors.END)


def validate_telegram_token(token: str) -> bool:
    """Validate Telegram bot token format."""
    pattern = r'^\d{8,10}:[A-Za-z0-9_-]{35}$'
    return bool(re.match(pattern, token))


def validate_user_id(user_id: str) -> bool:
    """Validate Telegram user ID format."""
    try:
        uid = int(user_id)
        return uid > 0
    except ValueError:
        return False


def validate_cloudflare_token(token: str) -> bool:
    """Validate Cloudflare API token format (basic check)."""
    return len(token) >= 20 and token.strip() != ""


def validate_zone_id(zone_id: str) -> bool:
    """Validate Cloudflare zone ID format (basic check)."""
    return len(zone_id) >= 20 and zone_id.strip() != ""


def get_telegram_bot_token() -> str:
    """Get Telegram bot token from user."""
    if RICH_AVAILABLE:
        console.print("\n[bold cyan]📱 Telegram Bot Configuration[/bold cyan]")
        console.print("[dim]Get your bot token from @BotFather on Telegram[/dim]\n")
    else:
        print(f"\n{Colors.CYAN}{Colors.BOLD}📱 Telegram Bot Configuration{Colors.END}")
        print(f"{Colors.YELLOW}Get your bot token from @BotFather on Telegram{Colors.END}\n")
    
    while True:
        token = Prompt.ask(
            "Enter your Telegram Bot Token",
            password=True
        ).strip()
        
        if not token:
            if RICH_AVAILABLE:
                console.print("[red]❌ Token cannot be empty![/red]")
            else:
                print(f"{Colors.RED}❌ Token cannot be empty!{Colors.END}")
            continue
        
        if validate_telegram_token(token):
            return token
        else:
            if RICH_AVAILABLE:
                console.print("[red]❌ Invalid token format![/red]")
                console.print("[yellow]Token should be in format: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz[/yellow]")
            else:
                print(f"{Colors.RED}❌ Invalid token format!{Colors.END}")
                print(f"{Colors.YELLOW}Token should be in format: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz{Colors.END}")


def get_admin_user_ids() -> List[int]:
    """Get admin user IDs from user."""
    if RICH_AVAILABLE:
        console.print("\n[bold cyan]👤 Admin User IDs[/bold cyan]")
        console.print("[dim]Get your Telegram user ID by messaging @userinfobot on Telegram[/dim]")
        console.print("[dim]You can add multiple admins separated by commas[/dim]\n")
    else:
        print(f"\n{Colors.CYAN}{Colors.BOLD}👤 Admin User IDs{Colors.END}")
        print(f"{Colors.YELLOW}Get your Telegram user ID by messaging @userinfobot on Telegram{Colors.END}")
        print(f"{Colors.YELLOW}You can add multiple admins separated by commas{Colors.END}\n")
    
    while True:
        user_ids_str = Prompt.ask(
            "Enter admin user ID(s) (comma-separated)"
        ).strip()
        
        if not user_ids_str:
            if RICH_AVAILABLE:
                console.print("[red]❌ At least one admin user ID is required![/red]")
            else:
                print(f"{Colors.RED}❌ At least one admin user ID is required!{Colors.END}")
            continue
        
        user_ids = [uid.strip() for uid in user_ids_str.split(',')]
        valid_ids = []
        invalid_ids = []
        
        for uid in user_ids:
            if validate_user_id(uid):
                valid_ids.append(int(uid))
            else:
                invalid_ids.append(uid)
        
        if invalid_ids:
            if RICH_AVAILABLE:
                console.print(f"[red]❌ Invalid user IDs: {', '.join(invalid_ids)}[/red]")
                console.print("[yellow]User IDs must be positive integers[/yellow]")
            else:
                print(f"{Colors.RED}❌ Invalid user IDs: {', '.join(invalid_ids)}{Colors.END}")
                print(f"{Colors.YELLOW}User IDs must be positive integers{Colors.END}")
            continue
        
        return valid_ids


def get_alert_chat_id() -> Optional[str]:
    """Get optional alert chat ID from user."""
    if RICH_AVAILABLE:
        console.print("\n[bold cyan]🔔 Alert Chat ID (Optional)[/bold cyan]")
        console.print("[dim]Leave empty if you don't want to receive alerts in a group[/dim]")
        console.print("[dim]For groups, get the chat ID (usually negative, e.g., -1001234567890)[/dim]\n")
    else:
        print(f"\n{Colors.CYAN}{Colors.BOLD}🔔 Alert Chat ID (Optional){Colors.END}")
        print(f"{Colors.YELLOW}Leave empty if you don't want to receive alerts in a group{Colors.END}")
        print(f"{Colors.YELLOW}For groups, get the chat ID (usually negative, e.g., -1001234567890){Colors.END}\n")
    
    chat_id = Prompt.ask(
        "Enter alert chat ID (or press Enter to skip)",
        default=""
    ).strip()
    
    if not chat_id:
        return None
    
    try:
        # Validate it's a valid integer
        int(chat_id)
        return chat_id
    except ValueError:
        if RICH_AVAILABLE:
            console.print("[yellow]⚠️  Invalid chat ID format, skipping...[/yellow]")
        else:
            print(f"{Colors.YELLOW}⚠️  Invalid chat ID format, skipping...{Colors.END}")
        return None


def get_cloudflare_config() -> dict:
    """Get Cloudflare API configuration from user."""
    if RICH_AVAILABLE:
        console.print("\n[bold cyan]☁️  Cloudflare API Configuration[/bold cyan]")
        console.print("[dim]Get your API token from: https://dash.cloudflare.com/profile/api-tokens[/dim]")
        console.print("[dim]Required permissions: Zone.Zone (Read), Zone.Analytics (Read), Zone.DNS (Edit), Zone.Firewall Services (Edit), Zone.Cache Purge (Purge)[/dim]\n")
    else:
        print(f"\n{Colors.CYAN}{Colors.BOLD}☁️  Cloudflare API Configuration{Colors.END}")
        print(f"{Colors.YELLOW}Get your API token from: https://dash.cloudflare.com/profile/api-tokens{Colors.END}")
        print(f"{Colors.YELLOW}Required permissions: Zone.Zone (Read), Zone.Analytics (Read), Zone.DNS (Edit), Zone.Firewall Services (Edit), Zone.Cache Purge (Purge){Colors.END}\n")
    
    config = {}
    
    # API Token
    while True:
        token = Prompt.ask(
            "Enter your Cloudflare API Token",
            password=True
        ).strip()
        
        if not token:
            if RICH_AVAILABLE:
                console.print("[red]❌ API token is required![/red]")
            else:
                print(f"{Colors.RED}❌ API token is required!{Colors.END}")
            continue
        
        if validate_cloudflare_token(token):
            config['api_token'] = token
            break
        else:
            if RICH_AVAILABLE:
                console.print("[red]❌ Invalid API token format![/red]")
            else:
                print(f"{Colors.RED}❌ Invalid API token format!{Colors.END}")
    
    # Zone ID
    while True:
        zone_id = Prompt.ask(
            "Enter your Cloudflare Zone ID"
        ).strip()
        
        if not zone_id:
            if RICH_AVAILABLE:
                console.print("[red]❌ Zone ID is required![/red]")
            else:
                print(f"{Colors.RED}❌ Zone ID is required!{Colors.END}")
            continue
        
        if validate_zone_id(zone_id):
            config['zone_id'] = zone_id
            break
        else:
            if RICH_AVAILABLE:
                console.print("[red]❌ Invalid Zone ID format![/red]")
            else:
                print(f"{Colors.RED}❌ Invalid Zone ID format!{Colors.END}")
    
    # Account ID (optional)
    account_id = Prompt.ask(
        "Enter your Cloudflare Account ID (optional, press Enter to skip)",
        default=""
    ).strip()
    
    if account_id:
        config['account_id'] = account_id
    
    return config


def test_configuration(config_data: dict) -> bool:
    """Test the configuration by making a simple API call."""
    if RICH_AVAILABLE:
        console.print("\n[yellow]🔍 Testing configuration...[/yellow]")
    else:
        print(f"\n{Colors.YELLOW}🔍 Testing configuration...{Colors.END}")
    
    try:
        # Test Telegram bot token
        import requests
        telegram_url = f"https://api.telegram.org/bot{config_data['TELEGRAM_BOT_TOKEN']}/getMe"
        resp = requests.get(telegram_url, timeout=10)
        if resp.status_code != 200:
            if RICH_AVAILABLE:
                console.print("[red]❌ Telegram bot token is invalid![/red]")
            else:
                print(f"{Colors.RED}❌ Telegram bot token is invalid!{Colors.END}")
            return False
        
        # Test Cloudflare API token and zone
        cf_headers = {
            "Authorization": f"Bearer {config_data['CLOUDFLARE_API_TOKEN']}",
            "Content-Type": "application/json"
        }
        cf_url = f"https://api.cloudflare.com/client/v4/zones/{config_data['CLOUDFLARE_ZONE_ID']}"
        resp = requests.get(cf_url, headers=cf_headers, timeout=10)
        if resp.status_code != 200:
            if RICH_AVAILABLE:
                console.print("[red]❌ Cloudflare API token or Zone ID is invalid![/red]")
                if resp.status_code == 401:
                    console.print("[yellow]   → Authentication failed. Check your API token.[/yellow]")
                elif resp.status_code == 403:
                    console.print("[yellow]   → Access forbidden. Check your API token permissions.[/yellow]")
                elif resp.status_code == 404:
                    console.print("[yellow]   → Zone not found. Check your Zone ID.[/yellow]")
            else:
                print(f"{Colors.RED}❌ Cloudflare API token or Zone ID is invalid!{Colors.END}")
                if resp.status_code == 401:
                    print(f"{Colors.YELLOW}   → Authentication failed. Check your API token.{Colors.END}")
                elif resp.status_code == 403:
                    print(f"{Colors.YELLOW}   → Access forbidden. Check your API token permissions.{Colors.END}")
                elif resp.status_code == 404:
                    print(f"{Colors.YELLOW}   → Zone not found. Check your Zone ID.{Colors.END}")
            return False
        
        if RICH_AVAILABLE:
            zone_data = resp.json()
            if zone_data.get('success') and zone_data.get('result'):
                zone_name = zone_data['result'].get('name', 'Unknown')
                console.print(f"[green]✅ Configuration test passed![/green]")
                console.print(f"[green]   Zone: {zone_name}[/green]")
        else:
            zone_data = resp.json()
            if zone_data.get('success') and zone_data.get('result'):
                zone_name = zone_data['result'].get('name', 'Unknown')
                print(f"{Colors.GREEN}✅ Configuration test passed!{Colors.END}")
                print(f"{Colors.GREEN}   Zone: {zone_name}{Colors.END}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        if RICH_AVAILABLE:
            console.print(f"[red]❌ Error testing configuration: {e}[/red]")
            console.print("[yellow]⚠️  Configuration saved, but test failed. Please verify manually.[/yellow]")
        else:
            print(f"{Colors.RED}❌ Error testing configuration: {e}{Colors.END}")
            print(f"{Colors.YELLOW}⚠️  Configuration saved, but test failed. Please verify manually.{Colors.END}")
        return False
    except ImportError:
        if RICH_AVAILABLE:
            console.print("[yellow]⚠️  'requests' library not available. Skipping test.[/yellow]")
        else:
            print(f"{Colors.YELLOW}⚠️  'requests' library not available. Skipping test.{Colors.END}")
        return True  # Continue anyway


def create_env_file(config_data: dict, env_path: Path) -> bool:
    """Create .env file with configuration."""
    try:
        env_content = f"""# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN="{config_data['TELEGRAM_BOT_TOKEN']}"
ADMIN_USER_IDS="{','.join(map(str, config_data['ADMIN_USER_IDS']))}"
"""
        
        if config_data.get('ALERT_CHAT_ID'):
            env_content += f'ALERT_CHAT_ID="{config_data["ALERT_CHAT_ID"]}"\n'
        else:
            env_content += 'ALERT_CHAT_ID=""\n'
        
        env_content += f"""
# Cloudflare API Configuration
CLOUDFLARE_API_TOKEN="{config_data['CLOUDFLARE_API_TOKEN']}"
"""
        
        if config_data.get('CLOUDFLARE_ACCOUNT_ID'):
            env_content += f'CLOUDFLARE_ACCOUNT_ID="{config_data["CLOUDFLARE_ACCOUNT_ID"]}"\n'
        
        env_content += f'CLOUDFLARE_ZONE_ID="{config_data["CLOUDFLARE_ZONE_ID"]}"\n'
        
        env_path.write_text(env_content, encoding='utf-8')
        return True
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[red]❌ Error creating .env file: {e}[/red]")
        else:
            print(f"{Colors.RED}❌ Error creating .env file: {e}{Colors.END}")
        return False


def print_summary(config_data: dict):
    """Print configuration summary."""
    if RICH_AVAILABLE:
        table = Table(title="Configuration Summary", box=box.ROUNDED, show_header=True)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green", overflow="fold")
        
        table.add_row("Telegram Bot Token", config_data['TELEGRAM_BOT_TOKEN'][:20] + "..." if len(config_data['TELEGRAM_BOT_TOKEN']) > 20 else config_data['TELEGRAM_BOT_TOKEN'])
        table.add_row("Admin User IDs", ", ".join(map(str, config_data['ADMIN_USER_IDS'])))
        table.add_row("Alert Chat ID", config_data.get('ALERT_CHAT_ID', 'Not set'))
        table.add_row("Cloudflare API Token", config_data['CLOUDFLARE_API_TOKEN'][:20] + "..." if len(config_data['CLOUDFLARE_API_TOKEN']) > 20 else config_data['CLOUDFLARE_API_TOKEN'])
        table.add_row("Cloudflare Zone ID", config_data['CLOUDFLARE_ZONE_ID'])
        if config_data.get('CLOUDFLARE_ACCOUNT_ID'):
            table.add_row("Cloudflare Account ID", config_data['CLOUDFLARE_ACCOUNT_ID'])
        
        console.print("\n")
        console.print(table)
    else:
        print(f"\n{Colors.CYAN}{Colors.BOLD}Configuration Summary:{Colors.END}\n")
        print(f"  Telegram Bot Token: {config_data['TELEGRAM_BOT_TOKEN'][:20]}...")
        print(f"  Admin User IDs: {', '.join(map(str, config_data['ADMIN_USER_IDS']))}")
        print(f"  Alert Chat ID: {config_data.get('ALERT_CHAT_ID', 'Not set')}")
        print(f"  Cloudflare API Token: {config_data['CLOUDFLARE_API_TOKEN'][:20]}...")
        print(f"  Cloudflare Zone ID: {config_data['CLOUDFLARE_ZONE_ID']}")
        if config_data.get('CLOUDFLARE_ACCOUNT_ID'):
            print(f"  Cloudflare Account ID: {config_data['CLOUDFLARE_ACCOUNT_ID']}")
        print()


def main():
    """Main installation function."""
    print_header()
    
    if RICH_AVAILABLE:
        console.print("[bold green]Welcome to the Cloudflare Telegram Bot installation wizard![/bold green]")
        console.print("[dim]This script will guide you through setting up your bot configuration.[/dim]\n")
    else:
        print(f"{Colors.GREEN}{Colors.BOLD}Welcome to the Cloudflare Telegram Bot installation wizard!{Colors.END}")
        print(f"{Colors.YELLOW}This script will guide you through setting up your bot configuration.{Colors.END}\n")
    
    # Collect configuration
    config_data = {}
    
    # Telegram configuration
    config_data['TELEGRAM_BOT_TOKEN'] = get_telegram_bot_token()
    config_data['ADMIN_USER_IDS'] = get_admin_user_ids()
    config_data['ALERT_CHAT_ID'] = get_alert_chat_id()
    
    # Cloudflare configuration
    cf_config = get_cloudflare_config()
    config_data['CLOUDFLARE_API_TOKEN'] = cf_config['api_token']
    config_data['CLOUDFLARE_ZONE_ID'] = cf_config['zone_id']
    if 'account_id' in cf_config:
        config_data['CLOUDFLARE_ACCOUNT_ID'] = cf_config['account_id']
    
    # Print summary
    print_summary(config_data)
    
    # Confirm
    if not Confirm.ask("\nDo you want to save this configuration?", default=True):
        if RICH_AVAILABLE:
            console.print("[yellow]Installation cancelled.[/yellow]")
        else:
            print(f"{Colors.YELLOW}Installation cancelled.{Colors.END}")
        return
    
    # Create .env file
    env_path = Path('.env')
    if env_path.exists():
        if not Confirm.ask(f"\n.env file already exists. Overwrite it?", default=False):
            if RICH_AVAILABLE:
                console.print("[yellow]Installation cancelled.[/yellow]")
            else:
                print(f"{Colors.YELLOW}Installation cancelled.{Colors.END}")
            return
    
    if RICH_AVAILABLE:
        console.print("\n[yellow]📝 Creating .env file...[/yellow]")
    else:
        print(f"\n{Colors.YELLOW}📝 Creating .env file...{Colors.END}")
    
    if not create_env_file(config_data, env_path):
        if RICH_AVAILABLE:
            console.print("[red]❌ Failed to create .env file![/red]")
        else:
            print(f"{Colors.RED}❌ Failed to create .env file!{Colors.END}")
        return
    
    if RICH_AVAILABLE:
        console.print("[green]✅ .env file created successfully![/green]")
    else:
        print(f"{Colors.GREEN}✅ .env file created successfully!{Colors.END}")
    
    # Test configuration
    test_config = test_configuration(config_data)
    
    # Final instructions
    if RICH_AVAILABLE:
        console.print("\n[bold green]🎉 Installation Complete![/bold green]\n")
        console.print("[bold]Next steps:[/bold]")
        console.print("  1. Install dependencies: [cyan]pip install -r requirements.txt[/cyan]")
        console.print("  2. Run the bot: [cyan]python bot.py[/cyan]")
        console.print("  3. Start chatting with your bot on Telegram!\n")
        if not test_config:
            console.print("[yellow]⚠️  Configuration test failed. Please verify your settings manually.[/yellow]\n")
    else:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 Installation Complete!{Colors.END}\n")
        print(f"{Colors.BOLD}Next steps:{Colors.END}")
        print(f"  1. Install dependencies: {Colors.CYAN}pip install -r requirements.txt{Colors.END}")
        print(f"  2. Run the bot: {Colors.CYAN}python bot.py{Colors.END}")
        print(f"  3. Start chatting with your bot on Telegram!\n")
        if not test_config:
            print(f"{Colors.YELLOW}⚠️  Configuration test failed. Please verify your settings manually.{Colors.END}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"\n[red]❌ An error occurred: {e}[/red]")
        else:
            print(f"\n{Colors.RED}❌ An error occurred: {e}{Colors.END}")
        sys.exit(1)
